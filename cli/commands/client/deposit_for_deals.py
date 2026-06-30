import sys

import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.client import _utils as client_utils
from cli.commands.client._client import client_address
from cli.services.contracts.erc20_contract import ERC20Contract
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.porep_market import PoRepMarket
from cli.services.contracts.types.deal import PoRepMarketDealState, PoRepMarketDealView
from cli.services.contracts.usdc_token import USDCToken
from cli.services.web3_service import Web3Service, EthAddress


@click.command()
@click.argument("deal_id", type=click.IntRange(min=0), required=False)
@click.option("--months", type=click.IntRange(min=1), default=1, show_default=True,
              help="Number of months to calculate required deposit amount for.")
def deposit_for_deals(deal_id: int | None = None, months: int = 1):
    """
    Deposit funds to FileCoinPay account for all ACCEPTED/ACTIVE deals or a given deal ID.

    DEAL_ID - Optional deal ID to deposit funds for. If not provided, deposits for all ACCEPTED/ACTIVE deals.
    """

    Web3Service().wait_for_pending_transactions(client_address())

    if deal_id is not None:
        deal_view = PoRepMarket().get_deal_view(deal_id)
        deal = deal_view.deal

        if deal.client_address != client_address():
            raise click.ClickException(f"Deal ID {deal_id} client address {deal.client_address} "
                                       f"does not match with connected client address {client_address()}")

        click.echo(f"Depositing for deal {deal_view}\n")

        if deal.state == PoRepMarketDealState.ACCEPTED:
            if deal.rail_id == 0 or not deal.validator_address:
                raise click.ClickException(f"Deal not initialized; run {sys.argv[0]} client init-accepted-deals {deal_id} first")

            else:
                utils.confirm(f"Deal ID {deal_id} is in ACCEPTED state; "
                              f"you might want to run {sys.argv[0]} client make-allocations {deal_id} first. Continue anyway?", abort=True)

        elif deal.state in [PoRepMarketDealState.REJECTED, PoRepMarketDealState.TERMINATED, PoRepMarketDealState.EXPIRED]:
            raise click.ClickException("Cannot deposit for REJECTED, TERMINATED or EXPIRED deals")

        elif deal.state != PoRepMarketDealState.ACTIVE:
            utils.confirm(f"Deal ID {deal_id} is in state {deal.state} != ACTIVE. Continue anyway?", abort=True)

        deal_views = [deal_view]
    else:
        deals = [deal for deal in commands_utils.get_client_deals(client_address())
                 if deal.state in (PoRepMarketDealState.ACCEPTED, PoRepMarketDealState.ACTIVE)]
        click.echo(f"Found {len(deals)} ACCEPTED/ACTIVE deal(s) for client address {client_address()}")

        if not deals:
            return

        if utils.confirm("Print deals?", default=True):
            click.echo(utils.json_pretty(deals))
            click.echo()

        deal_views = [PoRepMarket().get_deal_view(deal.deal_id) for deal in deals]

    _deposit_for_deals(deal_views, months)


# deposits funds to FileCoinPay account for X month of storing deals
def _deposit_for_deals(deal_views: list[PoRepMarketDealView], months: int):
    deals_per_token = {}

    for deal_view in deal_views:
        deals_per_token.setdefault(deal_view.payment.payment_token, []).append(deal_view)

    click.echo(f"Found {len(deals_per_token)} unique token(s) across {len(deal_views)} deal(s)")

    for deal_token, deals_for_token in deals_per_token.items():
        deal_token_symbol = ERC20Contract(deal_token).symbol()
        click.echo(f"\nProcessing token {deal_token_symbol} ({deal_token}) for {len(deals_for_token)} deal(s)")
        try:
            __deposit_for_deals(deals_for_token, months, deal_token, deal_token_symbol)
        except click.Abort:
            click.echo("Skipped this token")


def __deposit_for_deals(deal_views: list[PoRepMarketDealView], months: int, token_address: EthAddress, token_symbol: str):
    filecoinpay_account = FileCoinPay().get_account(token_address, client_address())
    token_decimals = ERC20Contract(token_address).decimals()

    filecoinpay_available_funds = filecoinpay_account.funds - filecoinpay_account.lockup_current
    filecoinpay_available_funds_str = utils.str_from_wei(filecoinpay_available_funds, token_decimals)

    sector_size_bytes = PoRepMarket().get_sector_size_bytes()
    total_required_amount = sum(client_utils.calculate_deposit_amount(deal_view.terms.requested_size_bytes,
                                                                      deal_view.payment.price_per_32_gib_per_month,
                                                                      months,
                                                                      sector_size_bytes) for deal_view in deal_views)
    total_required_amount_str = utils.str_from_wei(total_required_amount, token_decimals)

    deposit_amount = total_required_amount - filecoinpay_available_funds
    deposit_amount_str = utils.str_from_wei(deposit_amount, token_decimals)

    click.echo()
    click.echo(f"FileCoinPay account token balance: {filecoinpay_available_funds_str} {token_symbol}")
    click.echo(f"Total required amount to cover {len(deal_views)} deal(s) for {months} month(s): {total_required_amount_str} {token_symbol}")
    click.echo(f"FileCoinPay account missing balance: {deposit_amount_str if deposit_amount > 0 else 0} {token_symbol}")

    if deposit_amount <= 0:
        click.echo("Existing FileCoinPay funds is sufficient to cover required deposit amount for deals")
        return

    client_utils.deposit_to_filecoinpay(deposit_amount, USDCToken(token_address))
