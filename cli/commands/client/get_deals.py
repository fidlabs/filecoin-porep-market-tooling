import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.client._client import client_address
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.porep_market import PoRepMarketDealState
from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper


@click.command()
@click.argument("deal_id", type=click.IntRange(min=1))
def get_deal_manifest(deal_id: int):
    """
    Get deal manifest by deal ID.

    DEAL_ID - Deal ID to fetch manifest for.
    """

    deal = PoRepMarketViewHelper().get_deal_view(deal_id)
    manifest = commands_utils.fetch_manifest(deal.data.manifest_location, show_manifest=False, quiet=True, retries=10)
    click.echo(utils.json_pretty(manifest))


@click.command()
@click.argument("deal_id", type=click.IntRange(min=1))
def get_deal_rail(deal_id: int):
    """
    Get deal rail info by deal ID.

    DEAL_ID - Deal ID to fetch.
    """

    click.echo(FileCoinPay().get_rail(PoRepMarketViewHelper().get_deal_view(deal_id).deal.rail_id))


@click.command()
@click.argument("deal_id", type=click.IntRange(min=1))
def get_deal(deal_id: int):
    """
    Get deal by ID.

    DEAL_ID - Deal ID to fetch.
    """

    click.echo(PoRepMarketViewHelper().get_deal_view(deal_id))


@click.command()
@click.argument("state", required=False, type=click.Choice(PoRepMarketDealState.to_string_list(), case_sensitive=False))
def get_deals(state: str | None = None):
    """
    Get client's deals by state.

    STATE - Optional deal state to filter by.
    """

    _state = PoRepMarketDealState.from_web3(str(state)) if state else None
    click.echo(utils.json_pretty(commands_utils.get_client_deals(client_address(), _state)))
