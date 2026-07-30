import click

from cli import utils
from cli.commands.admin._admin import admin_signer, admin_address
from cli.services.contracts.filecoinpay_validator import FileCoinPayValidator
from cli.services.contracts.porep_market import PoRepMarket, PoRepMarketDealState, PoRepMarketDeal
from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper
from cli.services.contracts.validator_factory import ValidatorFactory
from cli.services.web3_service import Web3Service


# TODO ASAP verify this

def _terminate_proposed_deal(deal: PoRepMarketDeal) -> str:
    assert deal.state == PoRepMarketDealState.PROPOSED

    return PoRepMarket().reject_deal(deal.deal_id, admin_signer())


def _terminate_finalized_deal(deal: PoRepMarketDeal) -> str:
    assert deal.state == PoRepMarketDealState.FINALIZED

    validator_address = ValidatorFactory().get_instance(deal.deal_id)
    if validator_address != deal.validator_address:
        raise click.ClickException(f"Validator address {validator_address} does not match expected {deal.validator_address} for deal ID {deal.deal_id}")

    return FileCoinPayValidator(deal.validator_address).finalize_deal(admin_signer())


def _terminate_active_deal(deal: PoRepMarketDeal) -> str:
    assert deal.state == PoRepMarketDealState.ACTIVE
    assert deal.rail_id

    return FileCoinPayValidator(deal.validator_address).early_rail_termination(admin_signer())


def _terminate_accepted_deal(deal: PoRepMarketDeal) -> str:
    #
    def terminate_accepted_initialized_deal(deal: PoRepMarketDeal) -> str:
        assert deal.state == PoRepMarketDealState.ACCEPTED
        assert deal.rail_id

        return FileCoinPayValidator(deal.validator_address).early_rail_termination(admin_signer())

    def terminate_accepted_not_initialized_deal(deal: PoRepMarketDeal) -> str:
        assert deal.state == PoRepMarketDealState.ACCEPTED
        assert not deal.rail_id

        return PoRepMarket().reject_accepted_deal(deal.deal_id, admin_signer())

    assert deal.state == PoRepMarketDealState.ACCEPTED

    if deal.rail_id == 0:
        return terminate_accepted_not_initialized_deal(deal)
    else:
        return terminate_accepted_initialized_deal(deal)


@click.command()
@click.argument("deal_id", type=click.IntRange(min=1))
def terminate_deal(deal_id: int):
    """
    Terminate a deal early. Not all deals can be terminated.

    \b
    Calls:
    - `PoRepMarket.rejectDeal` for PROPOSED deals,
    - `PoRepMarket.rejectAcceptedDeal` for ACCEPTED deals without initialized FileCoinPay rail,
    - `FileCoinPayValidator.earlyRailTermination` for ACCEPTED/ACTIVE deals with initialized rail,
    - `FileCoinPayValidator.finalizeDeal` for FINALIZED deals.

    DEAL_ID - The ID of the deal to terminate.
    """

    Web3Service().wait_for_pending_transactions(admin_address())

    deal = PoRepMarketViewHelper().get_deal_view(deal_id).deal
    utils.confirm(f"Terminating deal ID {deal.deal_id}: {deal}", abort=True)

    if deal.state == PoRepMarketDealState.FINALIZED:
        tx_hash = _terminate_finalized_deal(deal)
    elif deal.state == PoRepMarketDealState.ACTIVE:
        tx_hash = _terminate_active_deal(deal)
    elif deal.state == PoRepMarketDealState.ACCEPTED:
        tx_hash = _terminate_accepted_deal(deal)
    elif deal.state == PoRepMarketDealState.PROPOSED:
        tx_hash = _terminate_proposed_deal(deal)
    else:
        raise click.ClickException(f"Deal ID {deal_id} is not in a state that can be terminated")

    click.echo(f"Deal ID {deal.deal_id} terminated: {tx_hash}")
