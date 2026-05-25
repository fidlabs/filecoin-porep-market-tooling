import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.porep_market import PoRepMarketDealState, PoRepMarket


@click.command()
@click.argument("deal_id", type=click.IntRange(min=0))
def get_deal_manifest(deal_id: int):
    """
    Get deal manifest by deal ID.

    DEAL_ID - Deal ID to fetch manifest for.
    """

    deal = PoRepMarket().get_deal_proposal(deal_id)
    manifest = commands_utils.fetch_manifest(deal.manifest_location, show_manifest=False, quiet=True, retries=10)
    click.echo(utils.json_pretty(manifest))


@click.command()
@click.argument("deal_id", type=click.IntRange(min=0))
def get_deal_rail(deal_id: int):
    """
    Get deal rail info by deal ID.

    DEAL_ID - Deal ID to fetch.
    """

    click.echo(FileCoinPay().get_rail(PoRepMarket().get_deal_proposal(deal_id).rail_id))


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
    Get all deals by state.

    \b
    Use `client --address <client_address> get-deals` to get deals for a specific client.
    Use `sp --organization <organization> get-deals` to get deals for a specific organization.
    Use `sp get-deals --provider-id <provider_id>` to get deals for a specific provider.

    STATE - Optional deal state to filter by.
    """

    click.echo(utils.json_pretty(commands_utils.get_all_deals(PoRepMarketDealState.from_string(state))))
