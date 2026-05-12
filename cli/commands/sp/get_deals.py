import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.sp._sp import sp_organization_address
from cli.services.contracts.porep_market import PoRepMarketDealState, PoRepMarket
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.web3_service import ActorId


def _get_deals(state: str | None = None, provider_id: str | None = None, deal_id: int | None = None):
    if deal_id is not None:
        return [PoRepMarket().get_deal_proposal(deal_id)]
    else:
        _state = PoRepMarketDealState.from_string(state)
        _provider_id = ActorId(provider_id) if provider_id else None

        if _provider_id:
            try:
                provider_info = SPRegistry().get_provider_info(_provider_id)
            except RuntimeError:
                return []

            organization_address = provider_info.organization_address
        else:
            organization_address = sp_organization_address()

        result = commands_utils.get_all_deals(_state, organization_address)

        if _provider_id:
            result = [deal for deal in result if deal.provider_id == _provider_id]

        return result


@click.command()
@click.argument("state", required=False, type=click.Choice(PoRepMarketDealState.to_string_list(), case_sensitive=False))
@click.option("--provider-id", required=False, help="Provider id to filter deals by.")
@click.option("--deal-id", required=False, type=click.IntRange(min=0), help="Deal id to fetch.")
def get_deals(state: str | None = None, provider_id: str | None = None, deal_id: int | None = None):
    """
    Get deals for the current SP.

    STATE - Deal state to filter by.
    """

    click.echo(utils.json_pretty(_get_deals(state, provider_id, deal_id)))
