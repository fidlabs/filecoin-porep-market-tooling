import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.services.contracts.porep_market import PoRepMarket


@click.command()
@click.argument("deal_id", type=click.IntRange(min=0))
def get_claims(deal_id: int):
    """
    Get DDO allocations claims for a deal.

    DEAL_ID - The ID of the deal to get DDO allocations claims for.
    """

    deal = PoRepMarket().get_deal_proposal(deal_id)
    claims = commands_utils.get_deal_claims(deal)

    click.echo(utils.json_pretty(claims))
