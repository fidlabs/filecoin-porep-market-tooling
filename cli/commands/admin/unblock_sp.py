import click

from cli import utils
from cli.commands.admin._admin import admin_private_key, admin_address
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.web3_service import Web3Service, ActorId


@click.command()
@click.argument("provider_id")
def unblock_sp(provider_id: str):
    """
    Unblock a Storage Provider in the SPRegistry Smart Contract.

    PROVIDER_ID - Storage Provider ID to unblock.
    """

    provider_actor_id = ActorId(provider_id)
    Web3Service().wait_for_pending_transactions(admin_address())
    provider = SPRegistry().get_provider_info(provider_actor_id)

    if not provider.blocked:
        raise click.ClickException(f"Storage Provider {provider.provider_id} is not blocked")

    click.confirm(f"Unblocking Storage Provider {provider.provider_id} : "
                  f"{utils.json_pretty(provider)}", abort=True)

    tx_hash = SPRegistry().unblock_provider(provider.provider_id, admin_private_key())
    click.echo(f"Storage Provider {provider.provider_id} unblocked: {tx_hash}")
