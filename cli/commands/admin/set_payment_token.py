import click

from cli import utils
from cli.commands.admin._admin import admin_address, admin_signer
from cli.services.contracts.erc20_contract import ERC20Contract
from cli.services.contracts.sp_registry import SPRegistry, SPRegistryTokenConfig
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import Web3Service, EthAddress


@click.command()
@click.argument("token_address")
@click.argument("allowed")
@click.argument("min_price_per_32_gib_per_month", type=click.FloatRange(min=0))
def set_payment_token(token_address: str, allowed: str, min_price_per_32_gib_per_month: float):
    """
    Set payment token configuration in the SPRegistry contract.

    \b
    TOKEN_ADDRESS - The address of the payment token to configure.
    ALLOWED - Whether the payment token is allowed (true/false).
    MIN_PRICE_PER_32_GIB_PER_MONTH - The minimum price per 32 GiB per month in decimal format (e.g., 1.5 for 1.5 USDC).  [x>=0]
    """

    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(admin_address())

    _token_address = EthAddress.from_any(token_address)
    current_config = SPRegistry().get_payment_token_config(_token_address)

    # noinspection PyArgumentList
    new_config = SPRegistryTokenConfig(
        allowed=utils.string_to_bool(allowed),
        min_price_per_32_gib_per_month=utils.to_wei(min_price_per_32_gib_per_month, ERC20Contract(_token_address).decimals())
    )

    utils.confirm(f"Setting new payment token config for {_token_address}. Current: {current_config} -> New: {new_config}", abort=True)

    tx_hash = SPRegistry().set_payment_token(_token_address, new_config, admin_signer())
    click.echo(f"New payment token set: {tx_hash}")
