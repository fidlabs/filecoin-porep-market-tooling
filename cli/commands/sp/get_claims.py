import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper


@click.command()
@click.argument("deal_id", type=click.IntRange(min=1))
def get_claims(deal_id: int):
    """
    Get DDO allocation claims for a deal.

    DEAL_ID - The ID of the deal to get DDO allocation claims for.
    """

    deal = PoRepMarketViewHelper().get_deal_view(deal_id)
    claims = commands_utils.get_deal_claims(deal.deal)

    click.echo(utils.json_pretty(claims))
