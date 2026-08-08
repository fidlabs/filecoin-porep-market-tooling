import click

from cli import utils
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.web3_service import ActorId, EthAddress


@click.command()
@click.argument('provider_id', required=False)
@click.option("--organization", help="Optional SP Organization to list SPs from.")
def get_sps(provider_id: str | None = None, organization: str | None = None):
    """
    Get PoRep Market registered info for the SP.

    PROVIDER_ID - Optional Storage Provider ID to query.
    """

    if provider_id:
        result = [SPRegistry().get_provider_view(ActorId(provider_id))]
    elif organization:
        result = SPRegistry().get_provider_views_by_organization(EthAddress.from_any(organization))
    else:
        result = SPRegistry().get_provider_views()

    click.echo(utils.json_pretty(result))
