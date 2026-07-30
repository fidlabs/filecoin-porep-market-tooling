import click

from cli import utils
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.contracts.usdc_token import USDCToken
from cli.services.web3_service import ActorId, EthAddress


@click.command()
@click.argument("provider_id")
@click.option("--payment-token", envvar="USDC_TOKEN", show_envvar=True,
              help="ERC20 token address to read the offer payment row for.  [default: USDC_TOKEN env var]")
def get_offers(provider_id: str, payment_token: str | None = None):
    """
    Get PoRep Market offers of a Storage Provider.

    PROVIDER_ID - Storage Provider ID to list offers for.
    """

    token = EthAddress(payment_token) if payment_token else USDCToken().address()
    offer_ids = SPRegistry().get_offers_by_provider(ActorId(provider_id))

    click.echo(utils.json_pretty([SPRegistry().get_offer_view(offer_id, token) for offer_id in offer_ids]))
