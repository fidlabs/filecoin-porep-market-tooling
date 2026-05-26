import click

from cli import utils
from cli.commands.client import _utils as client_utils
from cli.services.contracts.erc20_contract import ERC20Contract
from cli.services.contracts.usdc_token import USDCToken
from cli.services.web3_service import EthAddress


@click.command()
@click.argument("amount", type=click.FloatRange(min=0, min_open=True))
@click.argument("token_address", envvar="USDC_TOKEN")
def deposit_amount(amount: float, token_address: str):
    """
    Deposit a specified amount of ERC20 token to FileCoinPay account.

    AMOUNT - Amount of token to deposit in decimal format (e.g., 1.5 for 1.5 USDC).  [x>0]
    TOKEN_ADDRESS - Address of the ERC20 token to deposit.  [default: USDC_TOKEN env var]
    """

    _token_address = EthAddress(token_address)
    token_decimals = ERC20Contract(_token_address).decimals()

    client_utils.deposit_to_filecoinpay(utils.to_wei(amount, token_decimals), USDCToken(_token_address))
