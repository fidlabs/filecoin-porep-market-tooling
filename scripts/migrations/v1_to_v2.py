import os
import sys
from pathlib import Path

import click
from eth_typing import HexStr

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cli import _cli, utils
from cli._cli import is_dry_run
from cli.commands.admin import _admin
from cli.commands.migration_utils import migration_service
from cli.services.contracts.porep_market import (
    PoRepMarket,
    PoRepMarketDealRequest,
    PoRepMarketDealType,
)
from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper
from cli.services.contract_service import ContractService
from cli.services.contracts.datacap_evidence_adapter import DataCapEvidenceAdapter
from cli.services.contracts.erc20_contract import ERC20Contract
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.migration import MigrationMarker, MigrationPair, migration_manifest_location
from cli.services.txsigner import LotusWalletTxSigner, PrivateKeyTxSigner
from cli.services.web3_service import EthAddress, Web3Service
from scripts.migrations._contracts import OperationalFileCoinPay, OperationalLegacyValidator


@click.group()
@click.option("--admin-private-key", envvar="ADMIN_PRIVATE_KEY", hidden=True)
@click.option("--admin-lotus-wallet", envvar="ADMIN_LOTUS_WALLET", show_envvar=True)
@click.option("--dry-run", envvar="DRY_RUN", is_flag=True, help="Validate without allowing script writes.")
@click.option("--yes", "noninteractive", is_flag=True, help="Execute validated operations without prompting.")
@click.pass_context
def migrations(ctx,
               admin_private_key: str | None,
               admin_lotus_wallet: str | None,
               dry_run: bool,
               noninteractive: bool):
    """Operator-only V1-to-V2 migration commands."""
    ctx.ensure_object(dict)
    ctx.obj["noninteractive"] = noninteractive
    _admin.ADMIN_PRIVATE_KEY = admin_private_key
    _admin.ADMIN_LOTUS_WALLET = admin_lotus_wallet
    _cli.DRY_RUN = dry_run


def _confirm(ctx, message: str):
    if not ctx.obj["noninteractive"]:
        utils.confirm(message, abort=True)


@migrations.command("inventory")
@click.argument("v1_deal_id", type=click.IntRange(min=1), required=False)
def inventory(v1_deal_id: int | None):
    """Check which V1 deals meet the strict migration admission rules."""
    service = migration_service()
    deals = [service.source_market.get_deal(v1_deal_id)] if v1_deal_id else service.source_market.get_deals()
    for deal in deals:
        try:
            _, claims = service.source_inventory(deal.deal_id)
            click.echo(f"V1 {deal.deal_id}: eligible, {len(claims)} claim(s), {deal.size_bytes} bytes")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            click.echo(f"V1 {deal.deal_id}: skipped: {exc}")


@migrations.command("propose")
@click.argument("v1_deal_id", type=click.IntRange(min=1))
@click.argument("offer_id", type=click.IntRange(min=1))
@click.option("--print-only", is_flag=True, help="Validate and print the proposal without loading a signer.")
@click.pass_context
def propose(ctx, v1_deal_id: int, offer_id: int, print_only: bool):
    """Create one 180-day V2 deal for an eligible V1 deal and explicit offer."""
    if is_dry_run() and not print_only:
        raise click.ClickException("--dry-run signs transactions; use --print-only")
    service = migration_service()
    source, claims = service.source_inventory(v1_deal_id)
    existing = service.source_reference_targets(v1_deal_id)
    if existing:
        raise click.ClickException(f"V1 deal {v1_deal_id} already has V2 migration reference(s): {existing}")
    offer = SPRegistry().get_offer_view(offer_id)
    if not offer.active or offer.provider_id != source.provider:
        raise click.ClickException("Offer is inactive or belongs to a different provider")
    expected_token = utils.get_env_required("MIGRATION_PAYMENT_TOKEN", required_type=EthAddress.from_any)
    payment = next((row for row in offer.payments if row.token == expected_token and row.active), None)
    if payment is None:
        raise click.ClickException(f"Offer {offer_id} has no active expected payment token {expected_token}")
    epochs_in_day = PoRepMarket().get_epochs_in_month() // 30
    duration_epochs = 180 * epochs_in_day
    terms = offer.terms
    if ((terms.min_size_bytes and source.size_bytes < terms.min_size_bytes)
            or (terms.max_size_bytes and source.size_bytes > terms.max_size_bytes)
            or (terms.min_duration_epochs and duration_epochs < terms.min_duration_epochs)
            or (terms.max_duration_epochs and duration_epochs > terms.max_duration_epochs)):
        raise click.ClickException("The source size or 180-day duration is outside the selected offer bounds")
    marker = MigrationMarker(service.source_chain_id, service.trusted_source_market, source.deal_id)
    request = PoRepMarketDealRequest(
        manifest_hash=source.manifest_hash,
        requested_size_bytes=source.size_bytes,
        max_price_per_32_gib_per_month=payment.price_per_32_gib_per_month,
        manifest_location=migration_manifest_location(source.manifest_location, marker),
        payment_token_address=payment.token,
        duration_days=180,
        deal_type=PoRepMarketDealType.PUBLIC,
        required_slis=offer.slis,
    )
    source_rail = FileCoinPay().get_rail(source.rail_id)
    source_token = ERC20Contract(source_rail.token)
    target_token = ERC20Contract(payment.token)
    click.echo(
        f"V1 {source.deal_id} -> offer {offer_id}: provider {source.provider}, client {source.client}, "
        f"size {source.size_bytes}, claims {len(claims)}, duration {source.duration_days}d -> 180d, "
        f"price {utils.str_from_wei(source.price_per_32_gib_per_month, source_token.decimals())} "
        f"{source_token.symbol()} -> "
        f"{utils.str_from_wei(payment.price_per_32_gib_per_month, target_token.decimals())} "
        f"{target_token.symbol()}, SLIs {source.requirements} -> {offer.slis}, token {payment.token}"
    )
    if print_only:
        return
    market = PoRepMarket()
    adapter = DataCapEvidenceAdapter(market.get_global_evidence_adapter_address())
    if adapter.evidence_type().value != 10:
        raise click.ClickException("Configured global evidence adapter is not DataCap type 10")
    if adapter.get_porep_market_contract_address() != market.address():
        raise click.ClickException("Configured global evidence adapter belongs to a different PoRep Market")
    _confirm(ctx, "Create this V2 migration deal?")
    signer = _admin.admin_signer()
    Web3Service().ensure_no_pending_transactions(signer.address())
    tx = PoRepMarket().propose_deal_with_specific_offer(offer_id, request, source.client, signer)
    created = [event for event in tx.events if event.get("event") == "DealCreated"]
    if len(created) != 1:
        raise click.ClickException("Proposal succeeded but one authoritative DealCreated event was not decoded")
    target_id = int(created[0]["args"]["dealId"])
    pair = MigrationPair(marker, source, PoRepMarketViewHelper().get_deal_view(target_id))
    service.validate_pair(pair)
    service._validate_migration_policy(pair)
    service.verify_direct_creation(pair)
    click.echo(f"Created and verified V2 migration deal {target_id}")


def _service_signer():
    private_key = os.getenv("POREP_SERVICE_PRIVATE_KEY")
    if private_key:
        return PrivateKeyTxSigner(HexStr(private_key))
    wallet = os.getenv("POREP_SERVICE_LOTUS_WALLET")
    if wallet:
        return LotusWalletTxSigner(wallet, utils.get_env_required("POREP_SERVICE_LOTUS_TOKEN"))
    raise click.ClickException(
        "Set POREP_SERVICE_PRIVATE_KEY or POREP_SERVICE_LOTUS_WALLET and POREP_SERVICE_LOTUS_TOKEN"
    )


def _validate_active_target(service, pair):
    return service.validate_active_replacement(pair)


@migrations.command("close-v1-if-v2-active")
@click.argument("v2_deal_id", type=click.IntRange(min=1), required=False)
@click.option("--step", type=click.Choice(["admin", "service", "settle", "all"]), default="all", show_default=True)
@click.option("--print-only", is_flag=True, help="Validate and show the next close step without loading signers.")
@click.pass_context
def close_v1_if_v2_active(ctx, v2_deal_id: int | None, step: str, print_only: bool):
    """Stop and settle V1 only after its verified V2 replacement is ACTIVE."""
    if is_dry_run() and not print_only:
        raise click.ClickException("--dry-run signs transactions; use --print-only")
    service = migration_service()
    pairs = service.discover(deal_id=v2_deal_id)
    for error in service.discovery_errors:
        click.echo(error, err=True)
    if v2_deal_id is not None and not pairs:
        raise click.ClickException(f"V2 deal {v2_deal_id} is not an authoritative migration pair")
    for pair in pairs:
        try:
            pair = _validate_active_target(service, pair)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            click.echo(f"V2 {pair.target.deal.deal_id}: waiting: {exc}", err=True)
            continue
        validator = OperationalLegacyValidator(pair.source.validator)
        pay = OperationalFileCoinPay()
        current_epoch = Web3Service().get_block_number()
        try:
            rail = pay.get_rail(pair.source.rail_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if pay.is_rail_finalized(
                    pair.source.rail_id, current_epoch, pair.source.proposed_at_epoch):
                click.echo(f"V1 {pair.source.deal_id}: rail already finalized, skipped")
                continue
            click.echo(
                f"V1 {pair.source.deal_id}: waiting: rail {pair.source.rail_id} cannot be read and has no "
                f"RailFinalized event: {exc}",
                err=True,
            )
            continue
        try:
            if (rail.from_address != pair.source.client
                    or rail.operator != pair.source.validator
                    or rail.validator != pair.source.validator
                    or not rail.token
                    or not rail.to_address):
                raise click.ClickException("V1 rail identity has the wrong client/validator or an empty token/payee")
            admin_ready = validator.min_epochs_between_settlements() == 1 and rail.lockup_period == 0
            if rail.end_epoch and not admin_ready:
                raise click.ClickException(
                    f"V1 rail {pair.source.rail_id} ended before close prerequisites were applied; handle separately"
                )
            if rail.end_epoch == 0:
                if rail.payment_rate <= 0:
                    raise click.ClickException("V1 rail is open with a non-positive payment rate")
                end_epoch = validator.deal_end_epoch(
                    pair.source.deal_id, pair.source.proposed_at_epoch, current_epoch
                )
                if end_epoch <= current_epoch:
                    raise click.ClickException(
                        f"V1 service expired at epoch {end_epoch}; handle this rail separately"
                    )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            click.echo(f"V1 {pair.source.deal_id}: waiting: {exc}", err=True)
            continue
        click.echo(
            f"V2 {pair.target.deal.deal_id} ACTIVE; V1 {pair.source.deal_id} rail {pair.source.rail_id}: "
            f"admin_ready={admin_ready}, end_epoch={rail.end_epoch}"
        )
        if print_only:
            continue
        _confirm(ctx, f"Run close step {step} for V1 deal {pair.source.deal_id}?")
        with ContractService.batch_confirmation():
            if step in ("admin", "all"):
                signer = _admin.admin_signer()
                Web3Service().ensure_no_pending_transactions(signer.address())
                if validator.min_epochs_between_settlements() != 1:
                    validator.set_min_epochs_between_settlements(1, signer)
                rail = pay.get_rail(pair.source.rail_id)
                if rail.lockup_period != 0:
                    validator.update_lockup_period(0, signer)
                rail = pay.get_rail(pair.source.rail_id)
                if validator.min_epochs_between_settlements() != 1 or rail.lockup_period != 0:
                    raise click.ClickException("V1 close admin prerequisites did not become visible on chain")
            if step in ("service", "all"):
                pair = _validate_active_target(service, pair)
                rail = pay.get_rail(pair.source.rail_id)
                if validator.min_epochs_between_settlements() != 1 or rail.lockup_period != 0:
                    raise click.ClickException("Run and verify the admin close prerequisites before the service step")
                if rail.end_epoch == 0:
                    signer = _service_signer()
                    Web3Service().ensure_no_pending_transactions(signer.address())
                    validator.disable_future_rail_payments(signer)
                    rail = pay.get_rail(pair.source.rail_id)
                    if rail.end_epoch == 0:
                        raise click.ClickException("V1 rail disable transaction did not set an end epoch")
            if step in ("settle", "all"):
                rail = pay.get_rail(pair.source.rail_id)
                if rail.end_epoch == 0:
                    raise click.ClickException("V1 rail is still open; run the service step first")
                if rail.end_epoch > Web3Service().get_block_number():
                    raise click.ClickException(f"V1 rail cannot settle before end epoch {rail.end_epoch}")
                signer = _service_signer()
                Web3Service().ensure_no_pending_transactions(signer.address())
                pay.settle_rail(pair.source.rail_id, rail.end_epoch, signer)
                if not pay.is_rail_finalized(
                        pair.source.rail_id,
                        Web3Service().get_block_number(),
                        pair.source.proposed_at_epoch):
                    raise click.ClickException("V1 settle receipt did not produce a RailFinalized event")
        click.echo(f"V1 {pair.source.deal_id}: requested close step {step} completed")


if __name__ == "__main__":
    migrations()  # pylint: disable=no-value-for-parameter
