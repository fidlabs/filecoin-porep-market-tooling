import click

from cli import utils
from cli.commands.sp import _utils as sp_utils


@click.command()
@click.argument("deal_id", type=click.IntRange(min=0))
def get_allocations(deal_id: int):
    """
    Get client allocations for a deal.

    DEAL_ID - The ID of the deal to get allocations for.
    """

    click.echo(utils.json_pretty(sp_utils.get_deal_allocations_by_id(deal_id)))
