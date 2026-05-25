import click

from cli import utils
from cli.commands.client._client import client_address
from cli.services.contracts.erc20_contract import ERC20Contract
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.web3_service import EthAddress


@click.command()
@click.option("--token-address", envvar="USDC_TOKEN", show_envvar=True, required=True,
              help="ERC20 token address to ask for.")
def get_filecoinpay_account(token_address: str):
    """
    Get client's FileCoinPay account for the organization and token address.
    Note: PoRep Market currently supports USDC only.
    """

    _token_address = EthAddress(token_address)
    token = ERC20Contract(_token_address)
    token_symbol = token.symbol()
    token_decimals = token.decimals()
    account = FileCoinPay().get_account(_token_address, client_address())

    click.echo(utils.json_pretty(
        {
            "owner": str(client_address()),
            "token": {
                "address": str(_token_address),
                "name": token.name(),
                "symbol": token_symbol,
                "decimals": token_decimals,
                "balance": f"{utils.str_from_wei(token.balance_of(client_address()), token_decimals)} {token_symbol}"
            },
            "account": {
                "funds": f"{utils.str_from_wei(account.funds, token_decimals)} {token_symbol}",
                "account": account.__dict__
            }
        }
    ))
