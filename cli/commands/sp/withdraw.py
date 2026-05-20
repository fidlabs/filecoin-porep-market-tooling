import click

from cli.commands.sp import _utils as sp_utils
from cli.commands.sp._sp import sp_address
from cli.services.web3_service import Web3Service, EthAddress


@click.command()
@click.argument("amount", type=click.IntRange(min=0))
@click.option("--to", required=False, type=click.STRING, help="address")
def withdraw(amount: int, to: str | None = None):
    """
    Withdraw money from filecoin pay, if no --to argument given it will be withdrawn to the sender.

    AMOUNT - amount to withdraw in USDC smallest units (wei-equivalent, 6 decimals).
    Example: 1 USDC = 1000000.
    """

    Web3Service().wait_for_pending_transactions(sp_address())

    if to is None:
        sp_utils.withdraw(amount)
    else:
        sp_utils.withdraw_to(amount, EthAddress.from_any(to))

