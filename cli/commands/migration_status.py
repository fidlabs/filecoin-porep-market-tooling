import click

from cli.commands.migration_utils import describe_rail, epochs_to_days, gib, migration_service, rail_daily_cost
from cli.services.contracts.datacap_evidence_adapter import DataCapEvidenceAdapter
from cli.services.contracts.filecoinpay_validator import FileCoinPayRailStatus, FileCoinPayValidator
from cli.services.contracts.legacy_porep_market import LegacyDeal
from cli.services.contracts.porep_market import PoRepMarketDealState
from cli.services.contracts.porep_market_view_helper import PoRepMarketDealView, PoRepMarketViewHelper
from cli.services.migration import Claim, MigrationError, MigrationService, adapter_claim_ids
from cli.services.web3_service import ActorId, EthAddress, Web3Service

_MIGRATION_STATES = (PoRepMarketDealState.ACCEPTED, PoRepMarketDealState.ACTIVE)


def _target_line(service: MigrationService, source: LegacyDeal, target: PoRepMarketDealView, current_epoch: int, check_sectors: bool) -> list[str]:
    lines = [(f"  V2 deal {target.deal.deal_id}: {target.deal.state}, requested {gib(target.terms.requested_size_bytes)}, "
              f"duration {epochs_to_days(target.terms.duration_epochs)}")]
    adapter = DataCapEvidenceAdapter(target.deal.evidence_adapter_address)
    registered = set(adapter_claim_ids(adapter, target.deal.deal_id))
    source_ids = set(service.source_market.get_client_contract().allocation_ids(source.deal_id))
    lines.append(f"    claims adopted: {len(registered & source_ids)}/{len(source_ids)}"
                 + (f", foreign claims on adapter: {len(registered - source_ids)}" if registered - source_ids else ""))

    if target.deal.state == PoRepMarketDealState.ACCEPTED:
        rail = "not initialized (run client init-deal)"
        if target.deal.validator_address and target.deal.rail_id:
            status = FileCoinPayValidator(target.deal.validator_address).get_rail_status()
            rail = f"rail {target.deal.rail_id} {status}" + ("" if status == FileCoinPayRailStatus.PREPARED else " (expected PREPARED)")
        posting = "finished, waiting for activation" if adapter.is_datacap_posting_finished(target.deal.deal_id) else "open"
        lines.append(f"    V2 rail: {rail}; DataCap posting: {posting}")
    else:
        service_view = target.service
        lines.append(f"    V2 service: epochs {service_view.service_start_epoch} to {service_view.service_end_epoch} "
                     f"({epochs_to_days(service_view.service_end_epoch - current_epoch)} left)")
        source_rail = service.source_rail(source)
        if source_rail.end_epoch == 0 or current_epoch <= source_rail.end_epoch:
            overlap_until = source_rail.end_epoch or current_epoch + source_rail.lockup_period
            lines.append(f"    overlap: V1 still paying {rail_daily_cost(source_rail)}"
                         f"{' until epoch ' + str(overlap_until) if source_rail.end_epoch else ', run client close-v1-deal'}")

    if check_sectors and registered:
        claims = Web3Service().state_get_claims(source.provider)
        sectors = {Claim.from_rpc(claim_id, claims[str(claim_id)]).sector for claim_id in registered if str(claim_id) in claims}
        expirations = [int((Web3Service().state_sector_get_info(source.provider, sector) or {}).get("Expiration", 0)) for sector in sectors]
        if expirations:
            earliest = min(expirations)
            needed = target.service.service_end_epoch if target.deal.state == PoRepMarketDealState.ACTIVE else current_epoch + target.terms.duration_epochs
            verdict = "ok" if earliest >= needed else "too early, SP must run sp extend-deal-sectors"
            lines.append(f"    sectors: {len(sectors)}, earliest expiration epoch {earliest} vs needed {needed}: {verdict}")
    return lines


@click.command("migration-status")
@click.option("--client", "client_filter", help="Only deals of this client address (any format).")
@click.option("--provider", "provider_filter", help="Only deals of this provider actor ID.")
@click.option("--check-sectors", is_flag=True, help="Also read the sector expirations behind the adopted claims (slow).")
def migration_status(client_filter: str | None, provider_filter: str | None, check_sectors: bool):
    """
    Show the V1 to V2 migration state of every paying V1 deal. Read-only, no wallet needed.

    V2 deals are matched to V1 deals by the claim IDs already adopted on the V2 adapter, so a V2 deal
    shows up under its V1 deal only after `client adopt-v1-claims` registered at least one claim.
    """

    service = migration_service()
    client = EthAddress.from_any(client_filter) if client_filter else None
    provider = ActorId(provider_filter) if provider_filter else None
    current_epoch = service.web3.get_block_number()

    sources = [deal for deal in service.paying_source_deals(client) if provider is None or deal.provider == provider]
    targets = [view for view in PoRepMarketViewHelper().get_deal_views()
               if view.deal.state in _MIGRATION_STATES
               and (client is None or view.deal.client_address == client)
               and (provider is None or view.deal.provider_id == provider)]
    try:
        pairs = service.pair_by_claims(targets, sources)
    except MigrationError as exc:
        raise click.ClickException(str(exc)) from exc
    target_by_source = {source_id: next(view for view in targets if view.deal.deal_id == target_id) for target_id, source_id in pairs.items()}

    click.echo(f"Current epoch {current_epoch}; {len(sources)} paying V1 deal(s), {len(pairs)} with a V2 replacement in progress\n")
    for source in sources:
        click.echo(f"V1 deal {source.deal_id}: provider {source.provider}, {gib(source.size_bytes)}, "
                   f"{describe_rail(source.rail_id, service.source_rail(source), current_epoch)}")
        target = target_by_source.get(source.deal_id)
        if target is None:
            click.echo("  V2: no claims adopted yet (not proposed, or run client adopt-v1-claims)")
        else:
            for line in _target_line(service, source, target, current_epoch, check_sectors):
                click.echo(line)
        click.echo()

    candidates = [view for view in targets if view.deal.deal_id not in pairs and view.deal.state == PoRepMarketDealState.ACCEPTED]
    if candidates:
        click.echo("ACCEPTED V2 deals without adopted V1 claims:")
        for view in candidates:
            click.echo(f"  V2 deal {view.deal.deal_id}: client {view.deal.client_address}, provider {view.deal.provider_id}, "
                       f"requested {gib(view.terms.requested_size_bytes)}, proposed at epoch {view.deal.proposed_at_epoch}")
