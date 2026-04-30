import click

from cli import utils
from cli.commands.admin._admin import admin_private_key, admin_address
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.web3_service import Web3Service, ActorId


@click.command()
@click.argument("provider_id")
def unpause_sp(provider_id: str):
    """
    Unpause a Storage Provider in the SPRegistry Smart Contract.

    PROVIDER_ID - Storage Provider ID to unpause.
    """

    provider_actor_id = ActorId(provider_id)
    Web3Service().wait_for_pending_transactions(admin_address())
    provider = SPRegistry().get_provider_info(provider_actor_id)

    if not provider.paused:
        raise click.ClickException(f"Storage Provider {provider.provider_id} is not paused")

    click.confirm(f"Unpausing Storage Provider {provider.provider_id}: "
                  f"{utils.json_pretty(provider)}", abort=True)

    tx_hash = SPRegistry().unpause_provider(provider.provider_id, admin_private_key())
    click.echo(f"Storage Provider {provider.provider_id} unpaused: {tx_hash}")
