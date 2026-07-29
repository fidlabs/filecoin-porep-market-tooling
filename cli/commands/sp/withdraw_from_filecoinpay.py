import click

from cli.commands import utils as commands_utils
from cli.commands.sp._sp import sp_address, sp_signer
from cli.services.web3_service import EthAddress


@click.command()
@click.argument("to_address")
@click.argument("amount", type=click.FloatRange(min=0, min_open=True))
@click.argument("token_address", envvar="USDC_TOKEN")
def withdraw_from_filecoinpay(to_address: str, amount: float, token_address: str):
    """
    Withdraw funds from FileCoinPay account.

    \b
    TO_ADDRESS - Address / actor ID to withdraw to.
    AMOUNT - Amount of token to withdraw in decimal format (e.g., 1.5 for 1.5 USDC).  [x>0]
    TOKEN_ADDRESS - Address of the ERC20 token to withdraw.  [default: USDC_TOKEN env var]
    """

    commands_utils.withdraw_from_filecoinpay(to_address, amount, EthAddress(token_address), sp_address(), sp_signer())
