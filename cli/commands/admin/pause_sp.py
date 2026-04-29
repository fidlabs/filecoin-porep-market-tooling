import click

from cli import utils
from cli.commands.admin._admin import admin_private_key, admin_address
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.web3_service import Web3Service, ActorId


@click.command()
@click.argument("provider_id")
def pause_sp(provider_id: str):
    """
    Pause a Storage Provider in the SPRegistry Smart Contract.

    PROVIDER_ID - Storage Provider ID to pause.
    """
    
    providerActorId = ActorId(provider_id)
    Web3Service().wait_for_pending_transactions(admin_address())
    provider = SPRegistry().get_provider_info(providerActorId)

    if provider.paused:
        raise click.ClickException(f"Storage Provider {provider.provider_id} is already paused")

    click.confirm(f"Pausing Storage Provider {provider.provider_id}: "
                  f"{utils.json_pretty(provider)}", abort=True)

    tx_hash = SPRegistry().pause_provider(provider.provider_id, admin_private_key())
    click.echo(f"Storage Provider {provider.provider_id} paused: {tx_hash}")
