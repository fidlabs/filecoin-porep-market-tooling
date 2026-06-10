import click

from cli.commands import utils as commands_utils
from cli.commands.client._client import client_address, client_signer
from cli.services.contracts.porep_market import PoRepMarket
from cli.services.web3_service import Web3Service


@click.command()
@click.argument("deal_id", type=click.IntRange(min=0))
def reject_deal(deal_id: int):
    """
    Reject a deal proposal.

    DEAL_ID - The ID of the deal proposal to reject.
    """

    Web3Service().wait_for_pending_transactions(client_address())

    commands_utils.reject_deal(PoRepMarket().get_deal_proposal(deal_id), client_signer())
