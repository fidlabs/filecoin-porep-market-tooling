import click

from cli.commands.client import _utils as client_utils
from cli.commands.client._client import client_address
from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import Web3Service


@click.command()
@click.argument("deal_id", type=click.IntRange(min=1))
def finalize_deal(deal_id: int):
    """
    Finalize an active deal after service has finished.

    DEAL_ID - The ID of the deal to finalize.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(client_address())

    client_utils.finalize_deal(PoRepMarketViewHelper().get_deal_view(deal_id).deal)
