import click

from cli import utils
from cli.commands.admin._admin import admin_private_key, admin_address
from cli.services.contracts.filecoinpay_validator import FileCoinPayValidator
from cli.services.contracts.porep_market import PoRepMarket, PoRepMarketDealState, PoRepMarketDealProposal
from cli.services.contracts.validator_factory import ValidatorFactory
from cli.services.web3_service import Web3Service


def terminate_completed_deal(deal: PoRepMarketDealProposal) -> str:
    assert deal.state == PoRepMarketDealState.COMPLETED

    if result := ValidatorFactory().get_instance(deal.deal_id) != deal.validator_address:
        raise click.ClickException(f"Validator address {result} does not match expected {deal.validator_address} for deal id {deal.deal_id}")

    return FileCoinPayValidator(deal.validator_address).disable_future_rail_payments(deal.rail_id, admin_private_key())


def terminate_accepted_deal(deal: PoRepMarketDealProposal) -> str:
    assert deal.state == PoRepMarketDealState.ACCEPTED

    if deal.rail_id == 0:
        raise click.ClickException(f"Deal id {deal.deal_id} does not have a FileCoinPay rail set and cannot be terminated while in ACCEPTED state")

    raise RuntimeError("Not implemented")  # TODO


@click.command()
@click.argument("deal_id", type=click.IntRange(min=0))
def terminate_deal(deal_id: int):
    """
    Terminate a deal early. Not all deals can be terminated.

    DEAL_ID - Deal ID to terminate.
    """

    Web3Service().wait_for_pending_transactions(admin_address())
    deal = PoRepMarket().get_deal_proposal(deal_id)
    click.confirm(f"Terminating deal id {deal.deal_id}: {utils.json_pretty(deal)}", abort=True)

    if deal.state == PoRepMarketDealState.COMPLETED:
        tx_hash = terminate_completed_deal(deal)
    elif deal.state == PoRepMarketDealState.ACCEPTED:
        tx_hash = terminate_accepted_deal(deal)
    else:
        raise click.ClickException(f"Deal id {deal_id} is not in a state that can be terminated. Current state: {deal.state.name}")

    click.echo(f"Deal id {deal.deal_id} terminated: {tx_hash}")
