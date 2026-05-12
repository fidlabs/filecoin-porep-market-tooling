import click

from cli import utils
from cli.commands.admin._admin import admin_private_key, admin_address
from cli.services.contracts.filecoinpay_validator import FileCoinPayValidator
from cli.services.contracts.porep_market import PoRepMarket, PoRepMarketDealState, PoRepMarketDealProposal
from cli.services.contracts.validator_factory import ValidatorFactory
from cli.services.web3_service import Web3Service


def _terminate_completed_deal(deal: PoRepMarketDealProposal) -> str:
    assert deal.state == PoRepMarketDealState.COMPLETED

    validator_address = ValidatorFactory().get_instance(deal.deal_id)
    if validator_address != deal.validator_address:
        raise click.ClickException(f"Validator address {validator_address} does not match expected {deal.validator_address} for deal id {deal.deal_id}")

    return FileCoinPayValidator(deal.validator_address).terminate_rail(deal.rail_id, admin_private_key())


def _terminate_accepted_deal(deal: PoRepMarketDealProposal) -> str:
    def terminate_accepted_initialized_deal() -> str:
        assert deal.state == PoRepMarketDealState.ACCEPTED
        assert deal.rail_id

        raise RuntimeError("Not implemented")  # TODO

    def terminate_accepted_not_initialized_deal() -> str:
        assert deal.state == PoRepMarketDealState.ACCEPTED
        assert not deal.rail_id

        return PoRepMarket().reject_accepted_deal(deal.deal_id, admin_private_key())

    assert deal.state == PoRepMarketDealState.ACCEPTED

    if deal.rail_id == 0:
        return terminate_accepted_not_initialized_deal()
    else:
        return terminate_accepted_initialized_deal()


@click.command()
@click.argument("deal_id", type=click.IntRange(min=0))
def terminate_deal(deal_id: int):
    """
    Terminate a deal early. Not all deals can be terminated.

    DEAL_ID - The ID of the deal to terminate.
    """

    Web3Service().wait_for_pending_transactions(admin_address())
    deal = PoRepMarket().get_deal_proposal(deal_id)
    utils.confirm(f"Terminating deal id {deal.deal_id}: {deal}", abort=True)

    if deal.state == PoRepMarketDealState.COMPLETED:
        tx_hash = _terminate_completed_deal(deal)
    elif deal.state == PoRepMarketDealState.ACCEPTED:
        tx_hash = _terminate_accepted_deal(deal)
    else:
        raise click.ClickException(f"Deal id {deal_id} is not in a state that can be terminated")

    click.echo(f"Deal id {deal.deal_id} terminated: {tx_hash}")
