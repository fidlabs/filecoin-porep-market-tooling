import click

from cli import utils
from cli.commands.admin._admin import admin_address, admin_signer
from cli.services.contracts.porep_market import PoRepMarket
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import Web3Service


@click.command()
@click.argument("padding", type=click.IntRange(min=0, max=100))
def set_completion_padding(padding: int):
    """
    Set new deal activation padding.

    PADDING - New padding value to be set.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(admin_address())

    current_padding = PoRepMarket().get_deal_activation_padding()
    utils.confirm(f"Setting new deal activation padding. Current: {current_padding} -> New: {padding}", abort=True)

    tx_hash = PoRepMarket().set_deal_activation_padding(padding, admin_signer()).tx_hash
    click.echo(f"New activation padding set: {tx_hash}")
