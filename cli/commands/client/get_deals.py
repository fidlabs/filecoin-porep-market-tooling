import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.client._client import client_address
from cli.services.contracts.porep_market import PoRepMarketDealState, PoRepMarket


@click.command()
@click.argument("deal_id", type=click.IntRange(min=0))
def get_deal(deal_id: int):
    """
    Get deal by ID.

    DEAL_ID - Deal ID to fetch.
    """

    click.echo(PoRepMarket().get_deal_proposal(deal_id))


@click.command()
@click.argument("state", required=False, type=click.Choice(PoRepMarketDealState.to_string_list(), case_sensitive=False))
def get_deals(state: str | None = None):
    """
    Get client's deals by state.

    STATE - Optional deal state to filter by.
    """

    click.echo(utils.json_pretty(commands_utils.get_client_deals(client_address(), PoRepMarketDealState.from_string(state))))
