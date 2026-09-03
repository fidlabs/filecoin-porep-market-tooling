import click

from cli import utils
from cli.commands.sp._sp import sp_organization_address
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.web3_service import ActorId


@click.command()
@click.argument("provider_id", required=False)
def get_offers(provider_id: str | None = None):
    """
    Get PoRep Market offers for a given Storage Provider.

    PROVIDER_ID - Optional Storage Provider ID to list offers for.  [default: all SPs under current SP_ORGANIZATION address]
    """

    if provider_id is not None:
        offer_ids = SPRegistry().get_offers_by_provider(ActorId(provider_id))
    else:
        providers = SPRegistry().get_provider_views_by_organization(sp_organization_address())
        offer_ids = []

        for provider in providers:
            offer_ids.extend(SPRegistry().get_offers_by_provider(provider.provider_id))

    click.echo(utils.json_pretty([SPRegistry().get_offer_view(offer_id) for offer_id in offer_ids]))


@click.command()
@click.argument("offer_id", type=click.IntRange(min=1))
def get_offer(offer_id: int):
    """
    Get PoRep Market offer details for a given offer ID.

    OFFER_ID - Offer ID to fetch details for.
    """

    click.echo(utils.json_pretty(SPRegistry().get_offer_view(offer_id)))
