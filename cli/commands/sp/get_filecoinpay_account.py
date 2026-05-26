import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.sp._sp import sp_organization_address
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.web3_service import EthAddress


@click.command()
@click.argument("token_address", envvar="USDC_TOKEN", required=True)
@click.option("--owner", required=False,
              help="Address / actor ID of the FileCoinPay account owner.  [default: all payee addresses under current SP organization].")
def get_filecoinpay_account(token_address: str, owner: str | None = None):
    """
    Get FileCoinPay account.

    TOKEN_ADDRESS - ERC20 token address to ask for.  [default: USDC_TOKEN env var]
    """

    if not owner:
        providers = SPRegistry().get_providers_info_by_organization(sp_organization_address())
        payee_addresses = set(p.payee_address for p in providers)
    else:
        payee_addresses = {EthAddress.from_any(owner)}

    result = [commands_utils.get_filecoinpay_account(token_address, address) for address in payee_addresses]
    click.echo(utils.json_pretty(result))
