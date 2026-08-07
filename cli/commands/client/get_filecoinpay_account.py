import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.client._client import client_address
from cli.services.web3_service import EthAddress


@click.command()
@click.argument("token_address", envvar="USDC_TOKEN")
def get_filecoinpay_account(token_address: str):
    """
    Get FileCoinPay account.

    TOKEN_ADDRESS - ERC20 token address to ask for.  [default: USDC_TOKEN env var]
    """

    click.echo(utils.json_pretty(commands_utils.get_filecoinpay_account(EthAddress.from_any(token_address), client_address())))
