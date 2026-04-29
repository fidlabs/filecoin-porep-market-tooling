import click

from cli.commands.sp._sp import sp_address
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.web3_service import ActorId


@click.command()
@click.argument("provider_id")
def is_authorized(provider_id: str):
    """
    Check if your private key is authorized to manage deals for the given Storage Provider ID.

    PROVIDER_ID - Storage Provider ID to check authorization for.
    """

    click.echo(SPRegistry().is_authorized_for_provider(sp_address(), ActorId(provider_id)))
