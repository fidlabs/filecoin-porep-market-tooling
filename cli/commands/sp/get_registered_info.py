import click

from cli import utils
from cli.commands.sp._sp import sp_organization_address
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.web3_service import ActorId


@click.command()
@click.argument('provider_id', required=False)
def get_registered_info(provider_id: str | None = None):
    """
    Get PoRep Market registered info for the SP.

    PROVIDER_ID - Storage Provider id to query. [default: all providers under current SP organization]
    """

    _provider_id = ActorId(provider_id) if provider_id else None

    click.echo(utils.json_pretty(
        [SPRegistry().get_provider_info(_provider_id)] if _provider_id else
        SPRegistry().get_providers_info_by_organization(sp_organization_address())
    ))
