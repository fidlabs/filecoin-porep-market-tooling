import click

from cli import utils
from cli.commands.client import _utils as client_utils
from cli.commands.client._client import client_address
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.porep_market import PoRepMarketDealState, PoRepMarketDealProposal, PoRepMarket
from cli.services.contracts.usdc_token import USDCToken
from cli.services.web3_service import Web3Service


@click.command()
@click.argument("deal_id", type=click.IntRange(min=0), required=False)
@click.option("--months", type=click.IntRange(min=1), default=1, show_default=True,
              help="Number of months to calculate required deposit amount for.")
def deposit_for_deals(deal_id: int | None = None, months: int = 1):
    """
    Deposit USDC funds to FileCoinPay account for all COMPLETED deals or a given deal ID.

    DEAL_ID - Optional deal ID to deposit funds for. If not provided, deposits for all COMPLETED deals.
    """

    Web3Service().wait_for_pending_transactions(client_address())

    if deal_id is not None:
        deal = PoRepMarket().get_deal_proposal(deal_id)

        if deal.client_address != client_address():
            raise click.ClickException(f"Deal ID {deal_id} client address {deal.client_address} "
                                       f"does not match with connected client address {client_address()}")

        click.echo(f"Depositing for deal {deal}\n")

        if deal.state == PoRepMarketDealState.ACCEPTED:
            utils.confirm(f"Deal ID {deal_id} is in state ACCEPTED. You might want to initialize it first. Continue anyway?", abort=True)

        elif deal.state in [PoRepMarketDealState.REJECTED, PoRepMarketDealState.TERMINATED]:
            raise click.ClickException(f"Deal ID {deal_id} is in state {deal.state}. Cannot deposit for rejected or terminated deals.")

        elif deal.state != PoRepMarketDealState.COMPLETED:
            utils.confirm(f"Deal ID {deal_id} is in state {deal.state} != COMPLETED. Continue anyway?", abort=True)

        deals = [deal]
    else:
        deals = client_utils.get_client_deals(PoRepMarketDealState.COMPLETED)
        click.echo(f"Found {len(deals)} COMPLETED deal(s) for client address {client_address()}")

        if not deals:
            return

        if utils.confirm("Print deals?", default=True):
            click.echo(utils.json_pretty(deals))
            click.echo()

    _deposit_for_deals(deals, months)


# deposits USDC funds to FileCoinPay account for X month of storing deals
def _deposit_for_deals(deals: list[PoRepMarketDealProposal], months: int):
    filecoinpay_account = FileCoinPay().get_account(USDCToken().address(), client_address())

    token_decimals = USDCToken().decimals()
    token_name = USDCToken().name()

    filecoinpay_available_funds = filecoinpay_account.funds - filecoinpay_account.lockup_current
    filecoinpay_available_funds_str = utils.str_from_wei(filecoinpay_available_funds, token_decimals)

    total_required_amount = sum(client_utils.calculate_deposit_amount_for_deal(deal, months) for deal in deals)
    total_required_amount_str = utils.str_from_wei(total_required_amount, token_decimals)

    deposit_amount = total_required_amount - filecoinpay_available_funds
    deposit_amount_str = utils.str_from_wei(deposit_amount, token_decimals)

    click.echo()
    click.echo(f"FileCoinPay account token balance: {filecoinpay_available_funds_str} {token_name}")
    click.echo(f"Total required amount to cover {len(deals)} deal(s) for {months} month(s): {total_required_amount_str} {token_name}")
    click.echo(f"FileCoinPay account missing balance: {deposit_amount_str if deposit_amount > 0 else 0} {token_name}")

    if deposit_amount <= 0:
        click.echo("Existing FileCoinPay funds is sufficient to cover required deposit amount for deals")
        return

    client_utils.deposit_to_filecoinpay(deposit_amount)
