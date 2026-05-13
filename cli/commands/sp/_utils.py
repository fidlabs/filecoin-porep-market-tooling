import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.sp._sp import sp_private_key
from cli.services.contracts.client_contract import ClientContract
from cli.services.contracts.porep_market import PoRepMarketDealState, PoRepMarketDealProposal, PoRepMarket
from cli.services.web3_service import Web3Service


def accept_deal(deal: PoRepMarketDealProposal, confirm_session_id: str | None = None) -> str:
    if deal.state != PoRepMarketDealState.PROPOSED:
        raise click.ClickException(f"Deal ID {deal.deal_id} is not in PROPOSED state, current state: {deal.state}")

    utils.confirm(f"Accepting deal ID {deal.deal_id}: {deal}", default=True, abort=True, session_id=confirm_session_id)

    tx_hash = PoRepMarket().accept_deal(deal.deal_id, sp_private_key())
    click.echo(f"Deal ID {deal.deal_id} accepted: {tx_hash}")

    return tx_hash


def reject_deal(deal: PoRepMarketDealProposal, confirm_session_id: str | None = None) -> str:
    if deal.state != PoRepMarketDealState.PROPOSED:
        raise click.ClickException(f"Deal ID {deal.deal_id} is not in PROPOSED state, current state: {deal.state}")

    utils.confirm(f"Rejecting deal ID {deal.deal_id}: {deal}", default=True, abort=True, session_id=confirm_session_id)

    tx_hash = PoRepMarket().reject_deal(deal.deal_id, sp_private_key())
    click.echo(f"Deal ID {deal.deal_id} rejected: {tx_hash}")

    return tx_hash


def get_deal_allocations(deal: PoRepMarketDealProposal) -> list[dict]:
    manifest = commands_utils.fetch_manifest(deal.manifest_location, show_manifest=False, quiet=True, retries=10)
    pieces = manifest[0]["pieces"]

    deal_allocations = ClientContract().get_client_allocation_ids_per_deal(deal.deal_id)
    state_allocations = Web3Service().state_get_allocations(ClientContract().address().to_actor_id())

    return commands_utils.match_deal_allocations(pieces, state_allocations, deal_allocations)


def get_deal_allocations_by_id(deal_id: int) -> list[dict]:
    return get_deal_allocations(PoRepMarket().get_deal_proposal(deal_id))
