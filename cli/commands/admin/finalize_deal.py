import click

from cli import utils
from cli.commands.admin._admin import admin_address, admin_signer
from cli.services.contracts.porep_market import PoRepMarket, PoRepMarketDealState
from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import Web3Service


@click.command()
@click.argument("deal_id", type=click.IntRange(min=1))
def finalize_deal(deal_id: int):
    """
    Finalize an active deal after its service window has ended.

    DEAL_ID - The ID of the deal to finalize.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(admin_address())

    deal = PoRepMarketViewHelper().get_deal_view(deal_id).deal
    if deal.state != PoRepMarketDealState.ACTIVE:
        raise click.ClickException(f"Deal ID {deal_id} is in state {deal.state} != ACTIVE")

    utils.confirm(f"Finalizing deal ID {deal.deal_id}: {deal}", abort=True)

    tx_hash = PoRepMarket().finalize_deal(deal.deal_id, admin_signer())
    click.echo(f"Deal ID {deal.deal_id} finalized: {tx_hash}")
