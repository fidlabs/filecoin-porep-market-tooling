import click

from cli import utils
from cli.services.migration import MigrationError, MigrationPair, MigrationService
from cli.services.web3_service import ActorId, EthAddress


def migration_service() -> MigrationService:
    return MigrationService(
        utils.get_env_required("POREP_MARKET_V1", required_type=EthAddress.from_any),
        source_chain_id=utils.get_env_required("POREP_MARKET_V1_CHAIN_ID", required_type=int),
    )


def migration_pairs(*,
                    client: EthAddress | None = None,
                    provider: ActorId | None = None,
                    deal_id: int | None = None,
                    limit: int | None = None) -> tuple[MigrationService, list[MigrationPair]]:
    service = migration_service()
    try:
        pairs = service.discover(client=client, provider=provider, deal_id=deal_id, limit=limit)
    except MigrationError as exc:
        raise click.ClickException(str(exc)) from exc
    for error in service.discovery_errors:
        click.echo(error, err=True)
    if deal_id is not None and not pairs:
        details = service.discovery_errors[-1] if service.discovery_errors else "no migration marker"
        raise click.ClickException(f"V2 deal {deal_id} is not a verified migration deal: {details}")
    return service, pairs


def print_status(service: MigrationService, pairs: list[MigrationPair]):
    if not pairs:
        click.echo("No verified migration deals found.")
        return
    for pair in pairs:
        try:
            if pair.target.deal.state.name == "ACTIVE":
                pair = service.validate_active_replacement(pair)
                plan = None
            else:
                plan = service.adoption_plan(pair)
            action = service.next_action(pair, plan)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            action = f"operator review required: {exc}"
        click.echo(
            f"V2 {pair.target.deal.deal_id} <- V1 {pair.source.deal_id}: "
            f"{pair.target.deal.state}; {action}"
        )
