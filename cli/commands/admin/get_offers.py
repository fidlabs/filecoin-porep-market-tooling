import click

from cli import utils
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.web3_service import ActorId


@click.command()
@click.argument("provider_id", required=False)
def get_offers(provider_id: str | None = None):
    """
    Get PoRep Market offers of a Storage Provider.

    PROVIDER_ID - Storage Provider ID to list offers for. If not provided, lists offers for all providers.
    """

    if provider_id is not None:
        offer_ids = SPRegistry().get_offers_by_provider(ActorId(provider_id))
    else:
        provider_ids = SPRegistry().get_providers()
        offer_ids = []

        for provider_id in provider_ids:
            offer_ids.extend(SPRegistry().get_offers_by_provider(provider_id))

    click.echo(utils.json_pretty([SPRegistry().get_offer_view(offer_id) for offer_id in offer_ids]))
