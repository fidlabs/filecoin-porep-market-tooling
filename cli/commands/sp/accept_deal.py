import click

from cli.commands.sp import _utils as sp_utils
from cli.commands.sp._sp import sp_address
from cli.services.contracts.porep_market import PoRepMarket
from cli.services.web3_service import Web3Service


@click.command()
@click.argument("deal_id", type=click.IntRange(min=0))
# TODO LATER print deal state at the end?
def accept_deal(deal_id: int):
    """
    Accept a deal proposal.

    DEAL_ID - The ID of the deal proposal to accept.
    """

    Web3Service().wait_for_pending_transactions(sp_address())

    sp_utils.accept_deal(PoRepMarket().get_deal_proposal(deal_id))
