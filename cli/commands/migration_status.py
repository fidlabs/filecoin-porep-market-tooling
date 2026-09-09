import click

from cli.commands.migration_utils import migration_pairs, print_status
from cli.services.web3_service import ActorId, EthAddress


@click.command("migration-status")
@click.option("--deal-id", type=click.IntRange(min=1), help="Only this V2 deal ID.")
@click.option("--client-address", type=str, help="Only deals owned by this client.")
@click.option("--provider-id", type=str, help="Only deals for this provider actor ID.")
def migration_status(deal_id: int | None,
                     client_address: str | None,
                     provider_id: str | None):
    """Show verified V1-to-V2 migration state without loading a signer."""
    service, pairs = migration_pairs(
        client=EthAddress.from_any(client_address) if client_address else None,
        provider=ActorId(provider_id) if provider_id else None,
        deal_id=deal_id,
    )
    print_status(service, pairs)
