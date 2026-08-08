import click

from cli import utils
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.web3_service import ActorId, EthAddress


@click.command()
@click.argument("provider_id", required=False)
@click.option("--organization", help="Optional SP Organization to list offers for.")
def get_offers(provider_id: str | None = None, organization: str | None = None):
    """
    Get PoRep Market offers for a given Storage Provider.

    PROVIDER_ID - Optional Storage Provider ID to list offers for.
    """

    if provider_id is not None:
        offer_ids = SPRegistry().get_offers_by_provider(ActorId(provider_id))
    else:
        if organization:
            providers = SPRegistry().get_provider_views_by_organization(EthAddress.from_any(organization))
            provider_ids = [provider.provider_id for provider in providers]
        else:
            provider_ids = SPRegistry().get_providers()

        offer_ids = []

        for _provider_id in provider_ids:
            offer_ids.extend(SPRegistry().get_offers_by_provider(_provider_id))

    click.echo(utils.json_pretty([SPRegistry().get_offer_view(offer_id) for offer_id in offer_ids]))


@click.command()
@click.argument("offer_id", type=click.IntRange(min=1))
def get_offer(offer_id: int):
    """
    Get PoRep Market offer details for a given offer ID.

    OFFER_ID - Offer ID to fetch details for.
    """

    click.echo(utils.json_pretty(SPRegistry().get_offer_view(offer_id)))
