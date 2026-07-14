import click

from cli.commands.client import _utils as client_utils
from cli.commands.client._client import client_address
from cli.services.contracts.porep_market import PoRepMarket
from cli.services.web3_service import Web3Service


@click.command()
@click.argument("deal_id", type=click.IntRange(min=0))
def finalize_deal(deal_id: int):
    """
    Finalize an active deal after service has finished.

    DEAL_ID - The ID of the deal to finalize.
    """

    Web3Service().wait_for_pending_transactions(client_address())

    client_utils.finalize_deal(PoRepMarket().get_deal_view(deal_id).deal)
