import sys

import click

from cli import utils
from cli._cli import is_dry_run
from cli.commands.client._client import client_address, client_signer
from cli.commands.migration_utils import (
    describe_rail,
    epochs_to_days,
    gib,
    load_pair,
    migration_service,
    rail_daily_cost,
    token_info,
)
from cli.services.contract_service import ContractService
from cli.services.contracts.datacap_evidence_adapter import DataCapEvidenceAdapter
from cli.services.contracts.filecoin_pay import FileCoinPay, FileCoinPayRailView
from cli.services.contracts.filecoinpay_validator import FileCoinPayRailStatus, FileCoinPayValidator
from cli.services.contracts.porep_market import PoRepMarket, PoRepMarketDealState
from cli.services.migration import (
    ADOPTION_BATCH_SIZE,
    AdoptionPlan,
    MigrationError,
    MigrationPair,
    MigrationService,
    size_within_padding,
)
from cli.services.web3_service import Web3Service


def _require_client(pair: MigrationPair):
    if pair.source.client != client_address():
        raise click.ClickException(f"V1 deal {pair.source.deal_id} belongs to client {pair.source.client}, not {client_address()}")


def _plan(service: MigrationService, pair: MigrationPair, require_operational: bool) -> AdoptionPlan:
    try:
        return service.adoption_plan(pair, require_operational=require_operational)
    except MigrationError as exc:
        raise click.ClickException(str(exc)) from exc


def _print_pair(pair: MigrationPair, current_epoch: int):
    click.echo(f"V1 deal {pair.source.deal_id}: provider {pair.source.provider}, {gib(pair.source.size_bytes)}, "
               f"{describe_rail(pair.source.rail_id, pair.source_rail, current_epoch)}")
    click.echo(f"V2 deal {pair.target.deal.deal_id}: {pair.target.deal.state}, requested {gib(pair.target.terms.requested_size_bytes)}, "
               f"duration {epochs_to_days(pair.target.terms.duration_epochs)}")


def _print_plan(plan: AdoptionPlan):
    total = len(plan.source_claims)
    registered = len(plan.registered_ids)
    click.echo(f"V1 claims: {total}, already registered on the V2 adapter: {registered}, to adopt now: {len(plan.extensions)}")
    if plan.extensions:
        earliest = min(claim.end_epoch for claim in plan.source_claims)
        term_starts = {claim.claim_id: claim.term_start for claim in plan.source_claims}
        new_end = min(extension.new_term_max + term_starts[extension.claim_id] for extension in plan.extensions)
        click.echo(f"Earliest current claim end: epoch {earliest}; after adoption the adopted claims end at epoch {new_end} or later")


@click.command("adopt-v1-claims")
@click.argument("v2_deal_id", type=click.IntRange(min=1))
@click.argument("v1_deal_id", type=click.IntRange(min=1))
@click.option("--print-only", is_flag=True, help="Show the plan without loading a signer or sending anything.")
@click.option("--batch-size", type=click.IntRange(min=1, max=ADOPTION_BATCH_SIZE), default=ADOPTION_BATCH_SIZE, show_default=True,
              help="Claims per transaction.")
def adopt_v1_claims(v2_deal_id: int, v1_deal_id: int, print_only: bool, batch_size: int):
    """
    Move the DataCap claims of a V1 deal under a V2 deal.

    Extends the term of every V1 claim through the V2 DataCap evidence adapter, which registers the claims
    as evidence for the V2 deal. The V2 deal must be ACCEPTED and proposed for the same client and provider.
    Safe to re-run; already registered claims are skipped.

    Only works before the NV29 network upgrade, after which DataCap transfers are disabled on chain.

    V2_DEAL_ID - The V2 deal proposed as the replacement.

    V1_DEAL_ID - The V1 deal whose claims are adopted.
    """

    if is_dry_run() and not print_only:
        click.echo("Dry-run mode: acting as --print-only")
        print_only = True

    service = migration_service()
    pair = load_pair(service, v2_deal_id, v1_deal_id)
    _require_client(pair)
    plan = _plan(service, pair, require_operational=True)
    _print_pair(pair, service.web3.get_block_number())
    _print_plan(plan)

    if plan.complete:
        click.echo(f"\nAll V1 claims are registered. Next: `{sys.argv[0]} client init-deal {v2_deal_id}`, "
                   f"then `{sys.argv[0]} client finish-migration {v2_deal_id} {v1_deal_id}`.")
        return

    batches = plan.batches(batch_size)
    adapter = DataCapEvidenceAdapter(pair.target.deal.evidence_adapter_address)

    click.echo(f"\nPreflighting {len(batches)} transaction(s) from {client_address()}...")
    for number, batch in enumerate(batches, start=1):
        params = service.transfer_params(batch)
        operation = adapter.contract.functions.submitDataCapBatch((params.to, params.amount, params.operator_data), v2_deal_id)
        adapter.call_contract(operation, {"from": client_address()})
        gas = adapter.estimate_gas(operation, {"from": client_address()})
        click.echo(f"  batch {number}: {len(batch.extensions)} claim(s), estimated gas {gas}")

    if print_only:
        return

    utils.confirm(f"\nSend {len(batches)} transaction(s) adopting {len(plan.extensions)} V1 claim(s) into V2 deal {v2_deal_id}?", abort=True)
    signer = client_signer()
    try:
        Web3Service().ensure_no_pending_transactions(signer.address())
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    with ContractService.batch_confirmation():
        for number, batch in enumerate(batches, start=1):
            tx_hash = adapter.submit_datacap_batch(service.transfer_params(batch), v2_deal_id, signer).tx_hash
            click.echo(f"Batch {number}/{len(batches)} landed: {tx_hash}")
            try:
                service.validate_batch_receipt(pair, plan, batch)
            except MigrationError as exc:
                raise click.ClickException(f"Batch {number} landed but the chain readback does not match: {exc}; "
                                           f"stopping, re-run to continue") from exc

    final = _plan(service, pair, require_operational=False)
    if not final.complete:
        raise click.ClickException(f"{len(final.extensions)} claim(s) are still not registered; re-run the command")

    click.echo(f"\nAll {len(final.source_claims)} V1 claims are registered on V2 deal {v2_deal_id}.")
    click.echo(f"Next: `{sys.argv[0]} client init-deal {v2_deal_id}`, then `{sys.argv[0]} client finish-migration {v2_deal_id} {v1_deal_id}`.")


@click.command("finish-migration")
@click.argument("v2_deal_id", type=click.IntRange(min=1))
@click.argument("v1_deal_id", type=click.IntRange(min=1))
@click.option("--print-only", is_flag=True, help="Check readiness without loading a signer.")
def finish_migration(v2_deal_id: int, v1_deal_id: int, print_only: bool):
    """
    Close DataCap posting on a V2 deal that adopted all claims of a V1 deal.

    Requires `client init-deal` done for the V2 deal (validator and rail prepared) and every V1 claim
    registered on the V2 adapter. After this the PoRep Market service activates the deal.

    V2_DEAL_ID - The V2 deal to finish.

    V1_DEAL_ID - The V1 deal whose claims were adopted.
    """

    service = migration_service()
    pair = load_pair(service, v2_deal_id, v1_deal_id)
    _require_client(pair)
    target = pair.target
    _print_pair(pair, service.web3.get_block_number())

    if target.deal.state == PoRepMarketDealState.ACTIVE:
        click.echo(f"\nV2 deal {v2_deal_id} is already ACTIVE. Next: `{sys.argv[0]} client close-v1-deal {v1_deal_id} --v2-deal-id {v2_deal_id}`.")
        return
    if target.deal.state != PoRepMarketDealState.ACCEPTED:
        raise click.ClickException(f"V2 deal {v2_deal_id} is {target.deal.state}, expected ACCEPTED")

    adapter = DataCapEvidenceAdapter(target.deal.evidence_adapter_address)
    if adapter.is_datacap_posting_finished(v2_deal_id):
        click.echo(f"\nDataCap posting for V2 deal {v2_deal_id} is already finished; waiting for the service to activate the deal.")
        return

    if not target.deal.validator_address or not target.deal.rail_id:
        raise click.ClickException(f"V2 deal {v2_deal_id} has no payment rail yet; run `{sys.argv[0]} client init-deal {v2_deal_id}` first")
    rail_status = FileCoinPayValidator(target.deal.validator_address).get_rail_status()
    if rail_status != FileCoinPayRailStatus.PREPARED:
        raise click.ClickException(f"V2 deal {v2_deal_id} rail status is {rail_status}, expected PREPARED; "
                                   f"run `{sys.argv[0]} client init-deal {v2_deal_id}` first")

    plan = _plan(service, pair, require_operational=False)
    _print_plan(plan)
    if not plan.complete:
        raise click.ClickException(f"{len(plan.extensions)} V1 claim(s) are not registered on V2 deal {v2_deal_id}; "
                                   f"run `{sys.argv[0]} client adopt-v1-claims {v2_deal_id} {v1_deal_id}` first")

    allocated = adapter.get_allocated_bytes(v2_deal_id)
    requested = target.terms.requested_size_bytes
    padding = PoRepMarket().get_deal_activation_padding()
    if not size_within_padding(allocated, requested, padding):
        raise click.ClickException(f"Adapter bytes {allocated} are not within {padding / 100:.2f}% of the requested {requested}; "
                                   "ask the admin to fix the V2 manifest before finishing")
    click.echo(f"Adapter bytes {gib(allocated)} match the requested {gib(requested)} (padding {padding / 100:.2f}%)")

    if print_only:
        click.echo("\nReady to finish DataCap posting.")
        return

    utils.confirm(f"\nFinish DataCap posting for V2 deal {v2_deal_id}?", abort=True)
    tx_hash = adapter.finish_datacap_posting(v2_deal_id, client_signer()).tx_hash
    click.echo(f"DataCap posting finished: {tx_hash}")
    click.echo(f"The service activates the deal next; check with `{sys.argv[0]} migration-status --client {client_address()}`. "
               f"Once ACTIVE run `{sys.argv[0]} client close-v1-deal {v1_deal_id} --v2-deal-id {v2_deal_id}`.")


def _open_rail(rail_id: int) -> FileCoinPayRailView | None:
    try:
        return FileCoinPay().get_rail(rail_id)
    except click.ClickException as exc:
        if "RailInactiveOrSettled" in str(exc):
            return None
        raise


def _print_termination_preflight_help(rail: FileCoinPayRailView, current_epoch: int):
    symbol, decimals = token_info(rail.token)
    account = FileCoinPay().get_account_info_if_settled(rail.token, client_address())
    click.echo(f"FileCoinPay {symbol} account: funds {utils.str_from_wei(account.current_funds, decimals)}, "
               f"available {utils.str_from_wei(account.available_funds, decimals)}, funded until epoch {account.funded_until_epoch}")
    if account.funded_until_epoch < current_epoch:
        shortfall = account.current_lockup_rate * (current_epoch - account.funded_until_epoch + rail.lockup_period)
        click.echo(f"The account lockup is not settled up to the current epoch {current_epoch}. "
                   f"Deposit about {utils.str_from_wei(shortfall, decimals)} {symbol} with "
                   f"`{sys.argv[0]} client deposit-amount {utils.str_from_wei(shortfall, decimals)} {rail.token}` and re-run.")


@click.command("close-v1-deal")
@click.argument("v1_deal_id", type=click.IntRange(min=1))
@click.option("--v2-deal-id", type=click.IntRange(min=1), help="Replacement V2 deal; must be ACTIVE before the V1 rail is closed.")
@click.option("--print-only", is_flag=True, help="Show what would happen without loading a signer.")
def close_v1_deal(v1_deal_id: int, v2_deal_id: int | None, print_only: bool):
    """
    Stop paying for a V1 deal.

    Terminates the V1 Filecoin Pay rail; after the rail lockup period passes, re-run to settle and finalize it.
    The V1 settlement bot must not settle this rail in between. Payments overlap with the V2 deal until the
    rail end epoch, which is expected.

    V1_DEAL_ID - The V1 deal to close.
    """

    service = migration_service()
    source = service.source_deal(v1_deal_id)
    if source.client != client_address():
        raise click.ClickException(f"V1 deal {v1_deal_id} belongs to client {source.client}, not {client_address()}")
    current_epoch = service.web3.get_block_number()

    if v2_deal_id is not None:
        pair = load_pair(service, v2_deal_id, v1_deal_id, require_paying=False)
        if pair.target.deal.state != PoRepMarketDealState.ACTIVE:
            raise click.ClickException(f"V2 deal {v2_deal_id} is {pair.target.deal.state}, not ACTIVE; closing V1 now would leave a payment gap")
        click.echo(f"V2 deal {v2_deal_id} is ACTIVE since epoch {pair.target.service.service_start_epoch} "
                   f"({epochs_to_days(current_epoch - pair.target.service.service_start_epoch)} ago)")
    else:
        click.echo("Warning: no --v2-deal-id given, make sure the replacement V2 deal is ACTIVE before closing V1")

    if not source.rail_id:
        raise click.ClickException(f"V1 deal {v1_deal_id} has no payment rail")
    rail = _open_rail(source.rail_id)
    if rail is None:
        click.echo(f"V1 deal {v1_deal_id} rail {source.rail_id} is already settled and finalized; nothing to do.")
        return
    click.echo(f"V1 deal {v1_deal_id}: {describe_rail(source.rail_id, rail, current_epoch)}")

    if rail.end_epoch == 0:
        operation = FileCoinPay().contract.functions.terminateRail(source.rail_id)
        action = "terminate"
        click.echo(f"Terminating now stops payments at about epoch {current_epoch + rail.lockup_period} "
                   f"({epochs_to_days(rail.lockup_period)} from now, {rail_daily_cost(rail)} until then).")
    elif current_epoch <= rail.end_epoch:
        click.echo(f"Rail is terminated and still paying until epoch {rail.end_epoch} "
                   f"({epochs_to_days(rail.end_epoch - current_epoch)} from now); re-run after that to settle and finalize it.")
        return
    else:
        operation = FileCoinPay().contract.functions.settleTerminatedRailWithoutValidation(source.rail_id)
        action = "settle and finalize"
        click.echo(f"Rail end epoch {rail.end_epoch} has passed; settling pays the provider up to it and closes the rail.")

    try:
        FileCoinPay().call_contract(operation, {"from": client_address()})
    except click.ClickException as exc:
        click.echo(f"Preflight failed: {exc.message}")
        if action == "terminate":
            _print_termination_preflight_help(rail, current_epoch)
        raise click.ClickException(f"Cannot {action} rail {source.rail_id} right now") from exc

    if print_only:
        click.echo(f"\nReady to {action} rail {source.rail_id}.")
        return

    utils.confirm(f"\n{action.capitalize()} V1 rail {source.rail_id} of deal {v1_deal_id}?", abort=True)
    signer = client_signer()
    if action == "terminate":
        tx_hash = FileCoinPay().terminate_rail(source.rail_id, signer).tx_hash
        click.echo(f"Rail terminated: {tx_hash}")
        rail = _open_rail(source.rail_id)
        if rail is not None and rail.end_epoch:
            click.echo(f"Payments stop at epoch {rail.end_epoch}; re-run `{sys.argv[0]} client close-v1-deal {v1_deal_id}` after that to settle and finalize.")
    else:
        tx_hash = FileCoinPay().settle_terminated_rail_without_validation(source.rail_id, signer).tx_hash
        click.echo(f"Rail settled and finalized: {tx_hash}")
