import click

from cli.commands.sp import _utils as sp_utils
from cli.commands.sp._sp import sp_address
from cli.services.web3_service import Web3Service


@click.command()
def get_balance():
    """
    Get current balance.
    """

    Web3Service().wait_for_pending_transactions(sp_address())

    sp_utils.print_balance(sp_utils.get_balance(sp_address()))
