import click

from cli import utils
from cli.commands.sp import _utils as sp_utils
from cli.services.contracts.porep_market import PoRepMarket


@click.command()
@click.argument("deal_id", type=click.IntRange(min=0))
def get_allocations(deal_id: int):
    """
    Get client DDO allocations for a deal.

    DEAL_ID - The ID of the deal to get DDO allocations for.
    """

    deal = PoRepMarket().get_deal_proposal(deal_id)
    allocations = sp_utils.get_deal_allocations(deal)

    click.echo(utils.json_pretty(allocations))
