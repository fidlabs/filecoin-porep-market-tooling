import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.sp._sp import sp_organization_address
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.porep_market import PoRepMarketDealState
from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper
from cli.services.web3_service import ActorId


@click.command()
@click.argument("deal_id", type=click.IntRange(min=1))
def get_deal_manifest(deal_id: int):
    """
    Get deal manifest by deal ID.

    DEAL_ID - Deal ID to fetch manifest for.
    """

    deal = PoRepMarketViewHelper().get_deal_view(deal_id)
    manifest, _ = commands_utils.fetch_manifest(deal.data.manifest_location, show_manifest=False, quiet=True, retries=10)

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
@click.option("--provider-id", required=False, help="Provider ID to filter deals by.")
def get_deals(state: str | None = None, provider_id: str | None = None):
    """
    Get SP's deals by state and optionally by provider ID.

    STATE - Optional deal state to filter by.
    """

    _state = PoRepMarketDealState.from_web3(str(state)) if state else None
    result = commands_utils.get_sp_deals(_state,
                                         sp_organization_address() if not provider_id else None,
                                         ActorId(provider_id) if provider_id else None)

    click.echo(utils.json_pretty(result))
