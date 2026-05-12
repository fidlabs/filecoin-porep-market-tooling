import click

from cli import utils
from cli.commands.client import _utils as client_utils
from cli.services.contracts.usdc_token import USDCToken


@click.command()
@click.argument("amount", type=click.FloatRange(min=0, min_open=True))
def deposit_amount(amount: float):
    """
    Deposit a specified amount of USDC to FileCoinPay account.

    AMOUNT - Amount of USDC to deposit in decimal format (e.g., 1.5 for 1.5 USDC).  [x>0]
    """

    client_utils.deposit_to_filecoinpay(utils.to_wei(amount, USDCToken().decimals()))
