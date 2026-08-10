import click

from cli import utils
from cli.commands.admin._admin import admin_address, admin_signer
from cli.services.contracts.porep_market import (
    PoRepMarket,
    PoRepMarketDeal,
    PoRepMarketDealState,
)
from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import Web3Service


def _terminate_active_deal(deal: PoRepMarketDeal) -> str:
    assert deal.state == PoRepMarketDealState.ACTIVE
    assert deal.rail_id

    return PoRepMarket().terminate_deal(deal.deal_id, PoRepMarketDealState.EARLY_TERMINATED, admin_signer())


def _terminate_accepted_deal(deal: PoRepMarketDeal) -> str:
    assert deal.state == PoRepMarketDealState.ACCEPTED

    if deal.rail_id == 0:
        return PoRepMarket().reject_accepted_deal(deal.deal_id, admin_signer())
    else:
        return PoRepMarket().terminate_deal(deal.deal_id, PoRepMarketDealState.EARLY_TERMINATED, admin_signer())


@click.command()
@click.argument("deal_id", type=click.IntRange(min=1))
def terminate_deal(deal_id: int):
    """
    Terminate a deal early. Not all deals can be terminated.

    \b
    Calls:
    - `PoRepMarket.rejectAcceptedDeal` for ACCEPTED deals without initialized FileCoinPay rail,
    - `PoRepMarket.terminateDeal` for ACCEPTED/ACTIVE deals with initialized FileCoinPay rail.

    \b
    DEAL_ID - The ID of the deal to terminate.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(admin_address())

    deal = PoRepMarketViewHelper().get_deal_view(deal_id)
    utils.confirm(f"Terminating deal ID {deal.deal.deal_id}: {deal}", abort=True)

    if deal.deal.state == PoRepMarketDealState.ACTIVE:
        tx_hash = _terminate_active_deal(deal.deal)
    elif deal.deal.state == PoRepMarketDealState.ACCEPTED:
        tx_hash = _terminate_accepted_deal(deal.deal)
    else:
        raise click.ClickException(f"Deal ID {deal_id} is not in a state that can be terminated")

    click.echo(f"Deal ID {deal.deal.deal_id} terminated: {tx_hash}")
