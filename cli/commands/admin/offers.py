import click

from cli import utils
from cli.commands.admin._admin import admin_signer, admin_address
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.contracts.usdc_token import USDCToken
from cli.services.web3_service import Web3Service, ActorId


@click.command()
@click.argument("provider_id")
@click.option("--payment-token", envvar="USDC_TOKEN", show_envvar=True,
              help="ERC20 token address to read the offer payment row for.  [default: USDC_TOKEN env var]")
def get_offers(provider_id: str, payment_token: str | None = None):
    """
    Get PoRep Market offers of a Storage Provider.

    PROVIDER_ID - Storage Provider ID to list offers for.
    """

    token = payment_token or USDCToken().address()
    offer_ids = SPRegistry().get_offers_by_provider(ActorId(provider_id))
    click.echo(utils.json_pretty([SPRegistry().get_offer_view(offer_id, token) for offer_id in offer_ids]))


@click.command()
@click.argument("offer_id", type=click.IntRange(min=1))
@click.argument("active", type=bool)
def set_offer_active(offer_id: int, active: bool):
    """
    Enable or disable an offer for deal matching.

    \b
    OFFER_ID - The ID of the offer to modify.
    ACTIVE - true to enable the offer, false to disable it.
    """

    Web3Service().wait_for_pending_transactions(admin_address())

    view = SPRegistry().get_offer_view(offer_id, USDCToken().address())
    utils.confirm(f"Setting offer {offer_id} active={active}: {view}", abort=True)

    tx_hash = SPRegistry().set_offer_active(offer_id, active, admin_signer())
    click.echo(f"Offer {offer_id} active set to {active}: {tx_hash}")
