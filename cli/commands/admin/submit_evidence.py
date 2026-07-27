import time

import click
import eth_abi

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.admin._admin import admin_address, admin_signer
from cli.services.contracts.porep_market import PoRepMarket, PoRepMarketDealState
from cli.services.web3_service import Web3Service

# Matches oracle EVIDENCE_BATCH_SIZE default.
_DEFAULT_BATCH_SIZE = 1000


def _encode_batch_size(batch_size: int) -> bytes:
    return eth_abi.encode(["uint256"], [batch_size])


def _submit_one_batch(deal_id: int, batch_size: int) -> str:
    evidence_data = _encode_batch_size(batch_size)
    return PoRepMarket().submit_evidence_batch(deal_id, evidence_data, admin_signer())


@click.command("submit-evidence")
@click.argument("deal_id", type=click.IntRange(min=0))
@click.option(
    "--batch-size",
    type=click.IntRange(min=1),
    default=_DEFAULT_BATCH_SIZE,
    show_default=True,
    help="Max allocation IDs to process per submitEvidenceBatch call.",
)
@click.option(
    "--wait",
    "wait_for_claims",
    is_flag=True,
    default=False,
    help="Poll until VerifReg claims exist and all adapter allocation IDs move to claimIds.",
)
@click.option(
    "--timeout",
    type=click.IntRange(min=1),
    default=1800,
    show_default=True,
    help="Seconds to wait when --wait is set.",
)
@click.option(
    "--poll-interval",
    type=click.IntRange(min=1),
    default=15,
    show_default=True,
    help="Seconds between submit attempts when --wait is set.",
)
def submit_evidence(
    deal_id: int,
    batch_size: int = _DEFAULT_BATCH_SIZE,
    wait_for_claims: bool = False,
    timeout: int = 1800,
    poll_interval: int = 15,
):
    """
    Submit DataCap claim evidence for a deal (PoRepMarket.submitEvidenceBatch).

    Requires ADMIN_PRIVATE_KEY (or a wallet with POREP_SERVICE_ROLE / admin).
    evidenceData is abi.encode(uint256 batchSize): the adapter takes the next
    batchSize allocation IDs, calls VerifReg GetClaims, and moves successful IDs
    to claimIds.

    DEAL_ID - Deal to submit evidence for.
    """

    Web3Service().wait_for_pending_transactions(admin_address())

    market = PoRepMarket()
    deal = market.get_deal_view(deal_id).deal

    if deal.state not in (PoRepMarketDealState.ACCEPTED, PoRepMarketDealState.ACTIVE):
        raise click.ClickException(f"Deal ID {deal_id} is in state {deal.state}; expected ACCEPTED or ACTIVE")

    remaining = commands_utils.get_deal_allocation_ids(deal)
    claimed = commands_utils.get_deal_claim_ids(deal)

    if not remaining:
        click.echo(f"Deal ID {deal_id}: no pending allocation IDs (claims already recorded: {claimed})")
        return

    utils.confirm(
        f"Submit evidence for deal ID {deal_id}: {len(remaining)} allocation ID(s) pending, "
        f"{len(claimed)} claim ID(s) already recorded, batch_size={batch_size}"
        + (" (wait until VerifReg claims are ready)" if wait_for_claims else ""),
        default=True,
        abort=True,
    )

    deadline = time.monotonic() + timeout
    submitted_any = False

    while remaining:
        this_batch = min(batch_size, len(remaining))
        before = len(remaining)

        click.echo(
            f"Submitting evidence batch for deal {deal_id}: "
            f"batch_size={this_batch}, pending_allocation_ids={remaining}"
        )
        tx_hash = _submit_one_batch(deal_id, this_batch)
        click.echo(f"submitEvidenceBatch tx: {tx_hash}")
        submitted_any = True

        deal = market.get_deal_view(deal_id).deal
        remaining = commands_utils.get_deal_allocation_ids(deal)
        claimed = commands_utils.get_deal_claim_ids(deal)
        progressed = len(remaining) < before

        click.echo(
            f"Deal {deal_id}: pending_allocations={len(remaining)} claims={len(claimed)} "
            f"progressed={progressed}"
        )

        if not remaining:
            break

        if progressed:
            # Partial success — keep submitting without waiting.
            continue

        if not wait_for_claims:
            raise click.ClickException(
                f"Deal ID {deal_id}: submitEvidenceBatch moved 0 allocation IDs "
                f"(VerifReg claims not ready yet for {remaining}). "
                f"Re-run after Curio sealing, or use --wait."
            )

        if time.monotonic() >= deadline:
            raise click.ClickException(
                f"Deal ID {deal_id}: timed out after {timeout}s waiting for VerifReg claims "
                f"(still pending allocation IDs: {remaining})"
            )

        click.echo(f"No progress; waiting {poll_interval}s for Curio/VerifReg claims…")
        time.sleep(poll_interval)

    if submitted_any or claimed:
        click.echo(utils.json_pretty({"deal_id": deal_id, "claim_ids": claimed, "pending_allocation_ids": remaining}))
