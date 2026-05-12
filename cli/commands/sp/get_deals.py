import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.sp._sp import sp_organization_address
from cli.services.contracts.porep_market import PoRepMarketDealState, PoRepMarket
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.web3_service import ActorId


def _get_deals(state: PoRepMarketDealState | None = None, provider_id: ActorId | None = None):
    if provider_id:
        try:
            provider_info = SPRegistry().get_provider_info(provider_id)
        except RuntimeError:
            return []

        organization_address = provider_info.organization_address
    else:
        organization_address = sp_organization_address()

    result = commands_utils.get_all_deals(state, organization_address)

    if provider_id:
        result = [deal for deal in result if deal.provider_id == provider_id]

    return result


@click.command()
@click.argument("deal_id", type=click.IntRange(min=0))
def get_deal(deal_id: int):
    """
    Get deal by id.

    DEAL_ID - Deal id to fetch.
    """

    click.echo(PoRepMarket().get_deal_proposal(deal_id))


@click.command()
@click.argument("state", required=False, type=click.Choice(PoRepMarketDealState.to_string_list(), case_sensitive=False))
@click.option("--provider-id", required=False, help="Provider id to filter deals by.")
def get_deals(state: str | None = None, provider_id: str | None = None):
    """
    Get SP's deals by state and optionally by provider id.

    STATE - Optional deal state to filter by.
    """

    result = _get_deals(PoRepMarketDealState.from_string(state), ActorId(provider_id) if provider_id else None)
    click.echo(utils.json_pretty(result))
