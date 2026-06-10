import click

from cli import utils
from cli.commands.admin._admin import admin_signer, admin_address
from cli.services.contracts.porep_market import PoRepMarket
from cli.services.web3_service import Web3Service


@click.command()
@click.argument("padding", type=click.IntRange(min=0, max=100))
def set_completion_padding(padding: int):
    """
    Set new deal completion padding.

    PADDING - New padding value to be set.
    """

    Web3Service().wait_for_pending_transactions(admin_address())

    current_padding = PoRepMarket().get_deal_completion_padding()
    utils.confirm(f"Setting new deal completion padding. Current: {current_padding} -> New: {padding}", abort=True)

    tx_hash = PoRepMarket().set_deal_completion_padding(padding, admin_signer())
    click.echo(f"New padding set: {tx_hash}")
