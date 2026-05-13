import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.sp._sp import sp_organization_address
from cli.services.contracts.porep_market import PoRepMarketDealState, PoRepMarket
from cli.services.web3_service import ActorId


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
@click.option("--provider-id", required=False, help="Provider ID to filter deals by.")
def get_deals(state: str | None = None, provider_id: str | None = None):
    """
    Get SP's deals by state and optionally by provider ID.

    STATE - Optional deal state to filter by.
    """

    result = commands_utils.get_sp_deals(PoRepMarketDealState.from_string(state),
                                         sp_organization_address() if not provider_id else None,
                                         ActorId(provider_id) if provider_id else None)

    click.echo(utils.json_pretty(result))
