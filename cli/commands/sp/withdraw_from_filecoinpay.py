import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.sp._sp import sp_private_key, sp_address
from cli.services.contracts.erc20_contract import ERC20Contract
from cli.services.contracts.filecoin_pay import FileCoinPay
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

    _to_address = EthAddress.from_any(to_address)
    _token_address = EthAddress(token_address)

    token = ERC20Contract(_token_address)
    token_decimals = token.decimals()
    token_symbol = token.symbol()

    def print_token_balance(account_address: EthAddress):
        token_balance = token.balance_of(account_address)
        token_balance_str = utils.str_from_wei(token_balance, token_decimals)

        click.echo(f"Token balance of {account_address}: {token_balance_str} {token_symbol}")
        click.echo()

    print_token_balance(_to_address)
    click.echo(f"FileCoinPay account of {sp_address()}: " + utils.json_pretty(commands_utils.get_filecoinpay_account(token_address, sp_address())))
    click.echo()

    _amount = utils.to_wei(amount, token_decimals)
    amount_str = utils.str_from_wei(_amount, token_decimals)

    utils.confirm(f"Withdraw {amount_str} {token_symbol} from {sp_address()} FileCoinPay account to {_to_address}?", abort=True)

    tx_hash = FileCoinPay().withdraw_to(_token_address,
                                        EthAddress.from_any(to_address),
                                        _amount,
                                        sp_private_key())

    click.echo(f"Withdraw transaction sent: {tx_hash}")
    print_token_balance(_to_address)
