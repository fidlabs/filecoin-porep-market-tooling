import click

from cli import utils
from cli.commands.sp._sp import sp_signer
from cli.services.contracts.porep_market import PoRepMarketDealState, PoRepMarketDealProposal, PoRepMarket


def accept_deal(deal: PoRepMarketDealProposal, confirm_session_id: str | None = None) -> str:
    if deal.state != PoRepMarketDealState.PROPOSED:
        raise click.ClickException(f"Deal ID {deal.deal_id} is in state {deal.state} != PROPOSED")

    utils.confirm(f"Accepting deal ID {deal.deal_id}: {deal}", default=True, abort=True, session_id=confirm_session_id)

    tx_hash = PoRepMarket().accept_deal(deal.deal_id, sp_signer())
    click.echo(f"Deal ID {deal.deal_id} accepted: {tx_hash}")

    return tx_hash
