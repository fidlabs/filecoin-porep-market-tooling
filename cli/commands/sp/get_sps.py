import click

from cli import utils
from cli.commands.sp._sp import sp_organization_address
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.web3_service import ActorId, EthAddress


@click.command()
@click.argument('provider_id', required=False)
@click.option("--organization", help="SP Organization to query.  [default: SP_ORGANIZATION env var]")
def get_sps(provider_id: str | None = None, organization: str | None = None):
    """
    Get PoRep Market registered info for the SP.

    PROVIDER_ID - Storage Provider ID to query. [default: all providers under current SP organization]
    """

    click.echo(utils.json_pretty(
        [SPRegistry().get_provider_view(ActorId(provider_id))] if provider_id else
        SPRegistry().get_provider_views_by_organization(EthAddress.from_any(organization)
                                                        if organization
                                                        else sp_organization_address())
    ))
