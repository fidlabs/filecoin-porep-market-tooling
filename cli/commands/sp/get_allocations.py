import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.services.contracts.porep_market import PoRepMarket


@click.command()
@click.argument("deal_id", type=click.IntRange(min=0))
@click.option("--not-claimed", is_flag=True, default=False,
              help="Show only allocations that have not been claimed.  [default: False]")
def get_allocations(deal_id: int, not_claimed: bool = False):
    """
    Get client DDO allocations for a deal.

    DEAL_ID - The ID of the deal to get DDO allocations for.
    """

    deal = PoRepMarket().get_deal_proposal(deal_id)
    allocations = commands_utils.get_deal_allocations(deal)

    if not_claimed:
        claims = commands_utils.get_deal_claims(deal)
        allocations = {allocation_id: alloc for allocation_id, alloc in allocations.items() if allocation_id not in claims}

    click.echo(utils.json_pretty(allocations))
