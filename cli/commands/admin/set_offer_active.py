import click

from cli import utils
from cli.commands.admin._admin import admin_address, admin_signer
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import Web3Service


@click.command()
@click.argument("offer_id", type=click.IntRange(min=1))
@click.argument("active")
def set_offer_active(offer_id: int, active: str):
    """
    Enable or disable an offer for deal matching.

    \b
    OFFER_ID - The ID of the offer to modify.
    ACTIVE - true to enable the offer, false to disable it.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(admin_address())

    _active = utils.string_to_bool(active)
    assert _active is not None

    offer = SPRegistry().get_offer_view(offer_id)
    utils.confirm(f"Setting offer {offer_id} active={_active}: {offer}", abort=True)

    tx_hash = SPRegistry().set_offer_active(offer_id, _active, admin_signer())
    click.echo(f"Offer {offer_id} active set to {_active}: {tx_hash}")
