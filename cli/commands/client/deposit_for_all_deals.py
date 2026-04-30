import click

from cli import utils
from cli.commands.client import _utils as client_utils
from cli.commands.client._client import client_address, client_private_key
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.porep_market import PoRepMarketDealState, PoRepMarketDealProposal
from cli.services.contracts.usdc_token import USDCToken
from cli.services.web3_service import Address, Web3Service


@click.command()
@click.argument("months", type=click.IntRange(min=1), default=1)
def deposit_for_all_deals(months: int):
    """
    Deposit USDC funds to FileCoinPay account for all ACCEPTED deals.

    MONTHS - Number of months to calculate required deposit amount for. [default: 1; x>=1]
    """

    Web3Service().wait_for_pending_transactions(client_address())

    accepted_deals = client_utils.get_client_deals(PoRepMarketDealState.ACCEPTED)
    _deposit_for_all_deals(accepted_deals, months)


# deposits USDC funds to FileCoinPay account for X month of storing deals
def _deposit_for_all_deals(deals: list[PoRepMarketDealProposal], months: int):
    filecoinpay_account = FileCoinPay().get_account(utils.get_env_required("USDC_TOKEN", required_type=Address), client_address())

    token_decimals = USDCToken().decimals()
    token_name = USDCToken().name()

    token_balance = USDCToken().balance_of(client_address())
    token_balance_str = utils.str_from_wei(token_balance, token_decimals)

    filecoinpay_available_funds = filecoinpay_account.funds - filecoinpay_account.lockup_current
    filecoinpay_available_funds_str = utils.str_from_wei(filecoinpay_available_funds, token_decimals)

    total_required_amount = sum(client_utils.calculate_deposit_amount_for_deal(deal, months) for deal in deals)
    total_required_amount_str = utils.str_from_wei(total_required_amount, token_decimals)

    if filecoinpay_available_funds < total_required_amount:
        deposit_amount = total_required_amount - filecoinpay_available_funds
        deposit_amount_str = utils.str_from_wei(deposit_amount, token_decimals)

        permit_deadline = client_utils.get_permit_deadline()

        if token_balance < deposit_amount:
            raise click.ClickException(f"Address {client_address()} {token_name} balance {token_balance_str} {token_name} is "
                                       f"less than required deposit {deposit_amount_str} for {len(deals)} deals")

        click.confirm(
            f"\nDeposit {deposit_amount_str} {token_name} to {client_address()} FileCoinPay account for {len(deals)} deals\n"
            f"  Current token balance: {token_balance_str} {token_name}\n"
            f"  Current FileCoinPay account available funds: {filecoinpay_available_funds_str} {token_name}\n"
            f"  Total required funds for {len(deals)} deals for {months} months: {total_required_amount_str} {token_name}", abort=True)

        click.echo()
        signed_msg = client_utils.sign_filecoinpay_permit(deposit_amount, permit_deadline)
        tx_hash = FileCoinPay().deposit_with_permit(utils.get_env_required("USDC_TOKEN", required_type=Address),
                                                    client_address(),
                                                    deposit_amount,
                                                    permit_deadline,
                                                    signed_msg.v, utils.uint_to_bytes(signed_msg.r), utils.uint_to_bytes(signed_msg.s),
                                                    client_private_key())

        click.echo(f"Deposited {deposit_amount_str} {token_name}: {tx_hash}")
        return tx_hash
    else:
        click.echo(
            f"Existing FileCoinPay funds: {filecoinpay_available_funds_str} {token_name} is "
            f"sufficient for total required amount for all {len(deals)} ACCEPTED deals: {total_required_amount_str} {token_name}")
