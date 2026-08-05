import click

from cli.commands.sp import _utils as sp_utils
from cli.commands.sp._sp import sp_address
from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import Web3Service


@click.command()
@click.argument("deal_id", type=click.IntRange(min=1))
def accept_deal(deal_id: int):
    """
    Accept a deal proposal.

    DEAL_ID - The ID of the deal proposal to accept.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(sp_address())

    sp_utils.accept_deal(PoRepMarketViewHelper().get_deal_view(deal_id).deal)
