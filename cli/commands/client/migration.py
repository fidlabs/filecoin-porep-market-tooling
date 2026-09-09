import click
from dataclasses import dataclass
from contextlib import contextmanager

from cli import utils
from cli._cli import is_dry_run
from cli.commands.client import _utils as client_utils
from cli.commands.client._client import client_address, client_signer
from cli.commands.migration_utils import migration_pairs, print_status
from cli.services.contract_service import ContractService
from cli.services.contracts.datacap_evidence_adapter import DataCapEvidenceAdapter
from cli.services.contracts.erc20_contract import ERC20Contract
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.filecoinpay_validator import FileCoinPayRailStatus, FileCoinPayValidator
from cli.services.contracts.porep_market import PoRepMarketDealState
from cli.services.contracts.porep_market import PoRepMarket
from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper
from cli.services.contracts.validator_factory import ValidatorFactory
from cli.services.migration import MigrationError
from cli.services.web3_service import Web3Service


@click.command("migration-status")
@click.argument("deal_id", type=click.IntRange(min=1), required=False)
def migration_status(deal_id: int | None):
    """Show chain-derived migration state and the next action."""
    service, pairs = migration_pairs(client=client_address(), deal_id=deal_id)
    print_status(service, pairs)


@dataclass(frozen=True)
class AccountFundingRequirement:
    activation_reserve: int
    spending: int
    catch_up: int

    @property
    def total(self):
        return self.activation_reserve + self.spending + self.catch_up


def _validate_prepared_rail(view, owner):
    if not view.deal.rail_id:
        return None
    rail = FileCoinPay().get_rail(view.deal.rail_id)
    if (rail.from_address != owner
            or rail.to_address != view.payment.payee
            or rail.token != view.payment.payment_token
            or rail.operator != view.deal.validator_address
            or rail.validator != view.deal.validator_address
            or rail.payment_rate != 0
            or rail.end_epoch != 0
            or FileCoinPayValidator(view.deal.validator_address).get_rail_status()
            != FileCoinPayRailStatus.PREPARED):
        raise MigrationError("existing FileCoinPay rail is not the expected open PREPARED zero-rate rail")
    return rail


def _account_funding_by_token(owner, tokens=None, planned_unrailed_ids=frozenset()):
    """Return activation reserves plus 30-day spending for an account."""
    market = PoRepMarket()
    sector_size = market.get_sector_size_bytes()
    epochs_in_month = market.get_epochs_in_month()
    selected_tokens = set(tokens) if tokens is not None else None
    pending_monthly = {}
    pending_reserve = {}
    pay = FileCoinPay()
    for view in PoRepMarketViewHelper().get_deal_views():
        token = view.payment.payment_token
        if view.deal.client_address != owner or (selected_tokens is not None and token not in selected_tokens):
            continue
        if view.deal.state != PoRepMarketDealState.ACCEPTED:
            continue
        units = (view.terms.requested_size_bytes + sector_size - 1) // sector_size
        monthly_price = units * view.payment.price_per_32_gib_per_month
        forecast_rate = (monthly_price + epochs_in_month - 1) // epochs_in_month
        if view.deal.rail_id:
            try:
                rail = _validate_prepared_rail(view, owner)
            except MigrationError:
                continue
            lockup_period = rail.lockup_period
        elif view.deal.deal_id in planned_unrailed_ids:
            lockup_period = epochs_in_month
        else:
            continue
        amount = forecast_rate * epochs_in_month
        pending_monthly[token] = pending_monthly.get(token, 0) + amount
        pending_reserve[token] = pending_reserve.get(token, 0) + forecast_rate * lockup_period
    result = {}
    current_epoch = Web3Service().get_block_number()
    for token in (selected_tokens if selected_tokens is not None else pending_monthly):
        pending_spending = pending_monthly.get(token, 0)
        reserve = pending_reserve.get(token, 0)
        account = pay.get_account_info_if_settled(token, owner)
        spending = pending_spending + account.current_lockup_rate * epochs_in_month
        catch_up = max(0, current_epoch - account.funded_until_epoch) * account.current_lockup_rate
        result[token] = AccountFundingRequirement(reserve, spending, catch_up)
    return result


def _funding_by_token(pairs):
    pairs = list(pairs)
    tokens = {pair.target.payment.payment_token for pair in pairs}
    unrailed = {pair.target.deal.deal_id for pair in pairs if not pair.target.deal.rail_id}
    return _account_funding_by_token(client_address(), tokens, unrailed)


def _require_tx(tx, operation: str):
    tx_hash = tx if isinstance(tx, str) else tx.tx_hash
    if not tx_hash or tx_hash == Web3Service.ZERO_TX_HASH:
        raise click.ClickException(f"{operation} returned no authoritative transaction hash; stopping writes")


@contextmanager
def _operation_summary(label: str, total: int, waiting: int = 0, skipped: int = 0):
    counts = {"completed": 0, "skipped": skipped, "waiting": waiting}
    try:
        yield counts
    finally:
        click.echo(
            f"{label} summary: planned={total}, completed={counts['completed']}, "
            f"skipped={counts['skipped']}, waiting={counts['waiting']}"
        )


@click.command("prepare-migration")
@click.argument("deal_id", type=click.IntRange(min=1), required=False)
@click.option("--print-only", is_flag=True, help="Build and print the plan without loading a signer.")
def prepare_migration(deal_id: int | None, print_only: bool):
    """Fund rails and adopt all V1 claims into verified V2 deals."""
    if is_dry_run() and not print_only:
        raise click.ClickException("--dry-run still signs transactions; use --print-only for migration planning")
    service, pairs = migration_pairs(client=client_address(), deal_id=deal_id)
    plans = []
    waiting_count = 0
    skipped_count = 0
    for pair in pairs:
        if pair.target.deal.state == PoRepMarketDealState.ACTIVE:
            click.echo(f"V2 {pair.target.deal.deal_id}: already ACTIVE, skipped")
            skipped_count += 1
            continue
        if pair.target.deal.state != PoRepMarketDealState.ACCEPTED:
            click.echo(f"V2 {pair.target.deal.deal_id}: state {pair.target.deal.state}, skipped")
            skipped_count += 1
            continue
        try:
            _validate_prepared_rail(pair.target, client_address())
            plans.append((pair, service.adoption_plan(pair)))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            click.echo(f"V2 {pair.target.deal.deal_id}: preflight failed: {exc}", err=True)
            waiting_count += 1
    funding = _funding_by_token(pair for pair, _ in plans)
    approved_caps = {}
    click.echo(f"Prepared plan for {len(plans)} deal(s).")
    for token_address, requirement in funding.items():
        token = ERC20Contract(token_address)
        quote = client_utils.get_filecoinpay_funding_quote(requirement.total, token, client_address())
        approved_caps[token_address] = quote.deposit_amount
        click.echo(
            f"{token.symbol()}: activation reserve "
            f"{utils.str_from_wei(requirement.activation_reserve, token.decimals())}; "
            f"30-day spending {utils.str_from_wei(requirement.spending, token.decimals())}; "
            f"overdue catch-up {utils.str_from_wei(requirement.catch_up, token.decimals())}; "
            f"top-up {utils.str_from_wei(quote.deposit_amount, token.decimals())}"
        )
    for pair, plan in plans:
        click.echo(f"V2 {pair.target.deal.deal_id}: {len(plan.extensions)} V1 claim extension(s)")
    if print_only:
        return
    if not plans:
        with _operation_summary("Preparation", len(pairs), waiting_count, skipped_count):
            pass
        return
    utils.confirm("Execute this migration preparation batch?", abort=True)
    with _operation_summary("Preparation", len(pairs), waiting_count, skipped_count) as summary:
        signer = client_signer()
        Web3Service().ensure_no_pending_transactions(signer.address())
        with ContractService.batch_confirmation():
            for token_address in funding:
                token = ERC20Contract(token_address)
                refreshed_requirement = _account_funding_by_token(
                    client_address(),
                    {token_address},
                    {pair.target.deal.deal_id for pair, _ in plans if not pair.target.deal.rail_id},
                )[token_address]
                refreshed = client_utils.get_filecoinpay_funding_quote(
                    refreshed_requirement.total, token, client_address()
                )
                if refreshed.deposit_amount > approved_caps[token_address]:
                    raise click.ClickException(
                        f"{token.symbol()} top-up increased after confirmation; stopping before deposit"
                    )
                if refreshed.deposit_amount:
                    _require_tx(
                        client_utils.deposit_to_filecoinpay(
                            refreshed.deposit_amount, token, owner=client_address(), signer=signer, prompt=False
                        ),
                        f"FileCoinPay {token.symbol()} deposit",
                    )
            for pair, _ in plans:
                target_id = pair.target.deal.deal_id
                try:
                    current = PoRepMarketViewHelper().get_deal_view(target_id)
                    existing_rail = _validate_prepared_rail(current, client_address())
                    refreshed_pair = pair.__class__(
                        pair.marker, pair.source, current
                    )
                    plan = service.adoption_plan(refreshed_pair)
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    click.echo(f"V2 {target_id}: refreshed preflight failed: {exc}", err=True)
                    summary["waiting"] += 1
                    continue
                if current.deal.rail_id and plan.complete:
                    if existing_rail:
                        click.echo(f"V2 {target_id}: fully prepared, skipped")
                        summary["skipped"] += 1
                        continue
                if not current.deal.validator_address:
                    _require_tx(ValidatorFactory().create(target_id, signer), f"validator creation for V2 {target_id}")
                    current = PoRepMarketViewHelper().get_deal_view(target_id)
                approval = client_utils.approve_filecoinpay_operator(
                    ERC20Contract(current.payment.payment_token),
                    current.deal.validator_address,
                    client_address(),
                    signer,
                    prompt=False,
                )
                if approval is not None:
                    _require_tx(approval, f"FileCoinPay operator approval for V2 {target_id}")
                if not current.deal.rail_id:
                    _require_tx(
                        FileCoinPayValidator(current.deal.validator_address).create_rail(signer),
                        f"rail creation for V2 {target_id}",
                    )
                refreshed_pair = pair.__class__(
                    pair.marker, pair.source, PoRepMarketViewHelper().get_deal_view(target_id)
                )
                if plan.extensions:
                    adapter = DataCapEvidenceAdapter(refreshed_pair.target.deal.evidence_adapter_address)
                    deterministic_failure = False
                    for batch_number, planned_batch in enumerate(plan.batches(), start=1):
                        try:
                            batch = service.validate_outgoing_batch(refreshed_pair, plan, planned_batch)
                            params = service.transfer_params(batch)
                            operation = adapter.contract.functions.submitDataCapBatch(
                                (params.to, params.amount, params.operator_data), target_id
                            )
                            operation.call({"from": client_address()})
                            operation.estimate_gas({"from": client_address()})
                        except Exception as exc:  # pylint: disable=broad-exception-caught
                            click.echo(f"V2 {target_id}: claim batch preflight failed: {exc}", err=True)
                            summary["waiting"] += 1
                            deterministic_failure = True
                            break
                        _require_tx(
                            adapter.submit_datacap_batch(params, target_id, signer),
                            f"claim adoption batch {batch_number} for V2 {target_id}",
                        )
                        try:
                            service.validate_batch_receipt(refreshed_pair, plan, batch)
                        except Exception as exc:  # pylint: disable=broad-exception-caught
                            raise click.ClickException(
                                f"V2 {target_id} claim batch receipt is not authoritative: {exc}; stopping writes"
                            ) from exc
                    if deterministic_failure:
                        continue
                    verified_pair = pair.__class__(
                        pair.marker, pair.source, PoRepMarketViewHelper().get_deal_view(target_id)
                    )
                    verified = service.adoption_plan(verified_pair)
                    expected_ids = {claim.claim_id for claim in verified.source_claims}
                    if verified.extensions or verified.target_ids != expected_ids:
                        raise click.ClickException(
                            f"V2 {target_id} claim adoption did not produce the exact complete claim set; stopping writes"
                        )
                elif plan.complete:
                    click.echo(f"V2 {target_id}: claims already adopted, skipped")
                    summary["skipped"] += 1
                    continue
                summary["completed"] += 1


@click.command("finish-migration")
@click.argument("deal_id", type=click.IntRange(min=1), required=False)
@click.option("--print-only", is_flag=True, help="Check readiness without loading a signer.")
def finish_migration(deal_id: int | None, print_only: bool):
    """Close DataCap posting after all claims and sectors are ready."""
    if is_dry_run() and not print_only:
        raise click.ClickException("--dry-run still signs transactions; use --print-only for migration planning")
    service, pairs = migration_pairs(client=client_address(), deal_id=deal_id)
    ready = []
    waiting_count = 0
    skipped_count = 0
    for pair in pairs:
        target_id = pair.target.deal.deal_id
        if pair.target.deal.state == PoRepMarketDealState.ACTIVE:
            click.echo(f"V2 {target_id}: already ACTIVE, skipped")
            skipped_count += 1
            continue
        try:
            refreshed_pair, adapter = _finish_preflight(service, pair)
            if adapter.is_datacap_posting_finished(target_id):
                click.echo(f"V2 {target_id}: posting already finished, skipped")
                skipped_count += 1
                continue
            ready.append(refreshed_pair)
            click.echo(f"V2 {target_id}: ready to finish posting")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            click.echo(f"V2 {target_id}: waiting: {exc}")
            waiting_count += 1
    if print_only:
        return
    if not ready:
        with _operation_summary("Finish", len(pairs), waiting_count, skipped_count):
            pass
        return
    utils.confirm(f"Finish DataCap posting for {len(ready)} migration deal(s)?", abort=True)
    with _operation_summary("Finish", len(pairs), waiting_count, skipped_count) as summary:
        signer = client_signer()
        Web3Service().ensure_no_pending_transactions(signer.address())
        with ContractService.batch_confirmation():
            for pair in ready:
                target_id = pair.target.deal.deal_id
                try:
                    pair, adapter = _finish_preflight(service, pair)
                    posting_finished = adapter.is_datacap_posting_finished(target_id)
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    click.echo(f"V2 {target_id}: refreshed preflight failed: {exc}")
                    summary["waiting"] += 1
                    continue
                if posting_finished:
                    click.echo(f"V2 {target_id}: posting already finished, skipped")
                    summary["skipped"] += 1
                    continue
                _require_tx(adapter.finish_datacap_posting(target_id, signer), f"finish posting for V2 {target_id}")
                if not adapter.is_datacap_posting_finished(target_id):
                    raise click.ClickException(f"V2 {target_id} posting did not become finished; stopping writes")
                summary["completed"] += 1


def _finish_preflight(service, pair):
    target_id = pair.target.deal.deal_id
    pair = pair.__class__(pair.marker, pair.source, PoRepMarketViewHelper().get_deal_view(target_id))
    if pair.target.deal.state != PoRepMarketDealState.ACCEPTED:
        raise MigrationError(f"deal state is {pair.target.deal.state}, expected ACCEPTED")
    plan = service.adoption_plan(pair)
    source_ids = {claim.claim_id for claim in plan.source_claims}
    if plan.extensions or plan.target_ids != source_ids:
        raise MigrationError("not all V1 claims are pending or confirmed in V2")
    for claim in plan.source_claims:
        info = Web3Service().state_sector_get_info(pair.source.provider, claim.sector)
        expiration = int((info or {}).get("Expiration", (info or {}).get("expiration", 0)))
        if expiration < plan.sector_target_epoch:
            raise MigrationError(
                f"sector {claim.sector} expires at {expiration}, before target {plan.sector_target_epoch}"
            )
    if not pair.target.deal.rail_id:
        raise MigrationError("FileCoinPay rail is not prepared")
    rail = FileCoinPay().get_rail(pair.target.deal.rail_id)
    if (rail.from_address != client_address()
            or rail.to_address != pair.target.payment.payee
            or rail.token != pair.target.payment.payment_token
            or rail.operator != pair.target.deal.validator_address
            or rail.validator != pair.target.deal.validator_address
            or rail.payment_rate != 0
            or rail.end_epoch != 0):
        raise MigrationError("FileCoinPay prepared rail identity, rate, or end epoch is invalid")
    if FileCoinPayValidator(pair.target.deal.validator_address).get_rail_status() != FileCoinPayRailStatus.PREPARED:
        raise MigrationError("validator rail is not PREPARED")
    obligations = _account_funding_by_token(client_address(), {pair.target.payment.payment_token})
    token = ERC20Contract(pair.target.payment.payment_token)
    quote = client_utils.get_filecoinpay_funding_quote(
        obligations[pair.target.payment.payment_token].total, token, client_address()
    )
    if quote.deposit_amount:
        raise MigrationError(
            f"FileCoinPay account is short {quote.deposit_amount} base units for 30-day {token.symbol()} obligations"
        )
    return pair, DataCapEvidenceAdapter(pair.target.deal.evidence_adapter_address)
