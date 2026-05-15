import click

from cli import utils
from cli.services.contracts.client_contract import ClientContract
from cli.services.contracts.porep_market import PoRepMarket
from cli.services.web3_service import Web3Service


@click.command()
@click.argument("deal_id", type=click.IntRange(min=0))
def get_claims(deal_id: int):
    """
    Get DDO allocation claims for a deal.

    DEAL_ID - The ID of the deal to get DDO allocation claims for.
    """

    deal = PoRepMarket().get_deal_proposal(deal_id)
    deal_allocations = ClientContract().get_client_allocation_ids_per_deal(deal.deal_id)

    claims = Web3Service().state_get_claims(deal.provider_id, ClientContract().address().to_actor_id())
    claims = {claim_id: claim for claim_id, claim in claims.items() if int(claim_id) in deal_allocations}

    click.echo(utils.json_pretty(claims))
