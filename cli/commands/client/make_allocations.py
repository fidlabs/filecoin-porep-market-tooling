import sys
from pathlib import Path

import cbor2
import click
import multibase

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.client._client import client_address, client_signer
from cli.services.contracts.datacap_evidence_adapter import (
    DataCapEvidenceAdapter,
    DataCapTransferParams,
)
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.porep_market import PoRepMarket, PoRepMarketDealState
from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import ActorId, Web3Service


@click.command()
@click.argument("deal_id", type=click.IntRange(min=1))
@click.option("--print-only", is_flag=True, default=False,
              help="Print transfer params without broadcasting.  [default: false]")
@click.option("--exclude-dag", is_flag=True, default=False,
              help="Exclude manifest DAG piece. Default is to include it.  [default: false]")
@click.option("--local-manifest", type=click.Path(exists=True, dir_okay=False),
              help="Local manifest file to use instead of fetching from the deal proposal.")
def make_allocations(deal_id: int, print_only: bool = False, exclude_dag: bool = False, local_manifest: str | None = None):
    """
    Interactively make DDO allocations for an ACCEPTED deal in batches (groups).

    DEAL_ID: ID of the deal to make DDO allocations for.

    \b
    1. Fetch deal and manifest for the given DEAL_ID,
    2. prepare DataCap transfer parameters for each batch of pieces,
    3. make Direct Data Onboarding (DDO) allocation for each batch using the DataCap evidence adapter,
    4. finish DataCap posting to allow SP to submit the proof and receive payment.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(client_address())

    deal = PoRepMarketViewHelper().get_deal_view(deal_id)

    if deal.deal.state == PoRepMarketDealState.ACTIVE:
        click.echo(f"Deal ID {deal_id} is already ACTIVE; no more allocations need to be made.")
        return

    evidence_adapter = DataCapEvidenceAdapter(deal.deal.evidence_adapter_address)

    if evidence_adapter.is_datacap_posting_finished(deal_id):
        click.echo(f"DataCap posting for deal ID {deal_id} is already finished; no more allocations need to be made.")
        return

    if deal.deal.client_address != client_address():
        raise click.ClickException(f"Deal ID {deal_id} client address {deal.deal.client_address} "
                                   f"does not match with connected client address {client_address()}.")

    if deal.deal.state != PoRepMarketDealState.ACCEPTED:
        raise click.ClickException(f"Deal ID {deal_id} is in state {deal.deal.state} != ACCEPTED")

    if deal.deal.rail_id == 0:
        raise click.ClickException(f"Deal ID {deal_id} does not have a FileCoinPay rail set; "
                                   f"run `{sys.argv[0]} client init-deal` {deal_id} first.")

    if not deal.deal.validator_address:
        raise click.ClickException(f"Deal ID {deal_id} does not have a validator set; "
                                   f"run `{sys.argv[0]} client init-deal` {deal_id} first.")

    operator_approval = FileCoinPay().get_operator_approval(deal.payment.payment_token,
                                                            client_address(),
                                                            deal.deal.validator_address)

    if not operator_approval.is_approved:
        raise click.ClickException(f"Deal ID {deal_id} operator is not approved; "
                                   f"run `{sys.argv[0]} client init-deal` {deal_id} first.")

    deal_allocations = commands_utils.get_deal_allocations(deal.deal)
    deal_claims = commands_utils.get_deal_claims(deal.deal)

    click.echo(f"Found {len(deal_allocations)} allocations already made and {len(deal_claims)} claims for deal ID {deal_id}.")

    if deal_claims:
        raise RuntimeError("Some allocations claimed but deal still in ACCEPTED state.")

    if local_manifest:
        manifest, _ = commands_utils.fetch_local_manifest(Path(local_manifest).resolve())
    else:
        manifest, _ = commands_utils.fetch_manifest(deal.data.manifest_location, show_manifest=False)

    pieces = manifest[0]["pieces"]

    if exclude_dag:
        pieces = [piece for piece in pieces if piece["pieceType"] != "dag"]

    cids_allocated = [alloc.get("Data", {}).get("/") for alloc in [*deal_allocations.values(), *deal_claims.values()]]
    pieces_not_allocated = [piece for piece in pieces if piece["pieceCid"] not in cids_allocated]
    batches = _batch_pieces(pieces_not_allocated)

    utils.confirm(f"Continue with allocation of remaining {len(pieces_not_allocated)} pieces in {len(batches)} batches?", default=True, abort=True)

    EPOCHS_IN_MONTH = PoRepMarket().get_epochs_in_month()
    EPOCHS_IN_DAY = EPOCHS_IN_MONTH // 30  # PoRep Market smart contracts assumes month == 30 days
    assert EPOCHS_IN_DAY * 30 == EPOCHS_IN_MONTH

    term_min = deal.terms.duration_epochs
    term_max = term_min + 40 * EPOCHS_IN_DAY  # + 40 days

    for batch_idx, batch in enumerate(batches):
        current_batch_number = batch_idx + 1

        click.echo(f"\nBatch {current_batch_number}/{len(batches)} ({len(batch)} pieces):")
        for piece_cid, size in batch:
            data = {
                "pieceCid": piece_cid,
                "pieceSize": size
            }

            click.echo(f"  {utils.json_pretty(data)}")

        operator_data = _build_operator_data_batch(
            provider_id=deal.deal.provider_id,
            batch=batch,
            term_min=term_min,
            term_max=term_max,
            expiration=Web3Service().get_block_number() + EPOCHS_IN_MONTH
        )

        total_size = sum(size for _, size in batch)

        # noinspection PyArgumentList
        params = DataCapTransferParams(
            to=(b"\x00\x06",),
            amount=(utils.uint_to_bytes(utils.to_wei(total_size, utils.DATACAP_DECIMALS), size=None), False),
            operator_data=operator_data
        )

        if print_only:
            click.echo(f"to={params.to[0].hex()}\n"
                       f"amount={params.amount[0].hex()}\n"
                       f"operator_data={params.operator_data.hex()}")
        else:
            tx_hash = evidence_adapter.submit_datacap_batch(params, deal_id, client_signer()).tx_hash

            if tx_hash == Web3Service.ZERO_TX_HASH:
                click.echo("Cannot continue this command with dry-run mode, exiting.")
                return

            allocation_size = evidence_adapter.get_allocated_bytes(deal_id)
            click.echo(f"Batch {current_batch_number} done.")
            click.echo(f"Allocated size ({allocation_size}/{deal.terms.requested_size_bytes})")

    if not print_only:
        # pass deal_id to this function, since the deal object may be stale after each transaction
        _finish_datacap_posting(deal_id, manifest, exclude_dag)

    click.echo(f"\nAll done! Run `{sys.argv[0]} client deposit-for-deals {deal_id}` to deposit funds for this deal.")


def _finish_datacap_posting(deal_id: int, manifest: list[dict], exclude_dag: bool):
    Web3Service().wait_for_pending_transactions(client_address())
    deal = PoRepMarketViewHelper().get_deal_view(deal_id)

    # verify deal status
    if deal.deal.state != PoRepMarketDealState.ACCEPTED:
        raise click.ClickException(f"Deal ID {deal_id} is not in ACCEPTED state, current state: {deal.deal.state}")

    # verify all pieces are allocated
    deal_allocations = commands_utils.get_deal_allocations(deal.deal)
    deal_claims = commands_utils.get_deal_claims(deal.deal)
    cids_allocated = [alloc.get("Data", {}).get("/") for alloc in [*deal_allocations.values(), *deal_claims.values()]]

    pieces = manifest[0]["pieces"]

    if exclude_dag:
        pieces = [piece for piece in pieces if piece["pieceType"] != "dag"]

    pieces_not_allocated = [piece for piece in pieces if piece["pieceCid"] not in cids_allocated]

    if pieces_not_allocated:
        raise click.ClickException(f"Cannot finish DataCap posting for deal ID {deal_id}: {len(pieces_not_allocated)} pieces not allocated yet; "
                                   f"run `{sys.argv[0]} client make-allocations {deal_id}` again to allocate remaining pieces before finishing DataCap posting.")

    # verify allocated size is within padding range
    final_allocation_size = DataCapEvidenceAdapter(deal.deal.evidence_adapter_address).get_allocated_bytes(deal_id)
    padding = PoRepMarket().get_deal_activation_padding()
    proposed_size = deal.terms.requested_size_bytes
    delta = abs(final_allocation_size - proposed_size)

    if delta * 100 > proposed_size * padding:
        raise click.ClickException(f"Allocated size {final_allocation_size} is not within padding range of "
                                   f"proposed size {proposed_size} (padding: {padding * 100}%, delta: {delta})")

    # finish DataCap posting
    utils.confirm(f"Finishing DataCap posting for deal id {deal_id} (blocks further allocation batches)", default=True, abort=True)

    tx_hash = DataCapEvidenceAdapter(deal.deal.evidence_adapter_address).finish_datacap_posting(deal_id, client_signer()).tx_hash
    click.echo(f"DataCap posting for deal id {deal_id} finished: {tx_hash}")


def _build_operator_data_batch(provider_id: ActorId,
                               batch: list[tuple[str, int]],
                               term_min: int,
                               term_max: int,
                               expiration: int) -> bytes:
    #
    def format_cid_to_cbor_universal(cid_str: str) -> cbor2.CBORTag:
        try:
            cid_bytes = bytes(multibase.decode(cid_str))
        except Exception as e:
            raise click.ClickException(f"Invalid piece CID '{cid_str}': {e}") from e

        cid_with_prefix = b"\x00" + cid_bytes
        return cbor2.CBORTag(42, cid_with_prefix)

    entries = []

    for piece_cid, size in batch:
        entries.append([
            provider_id,
            format_cid_to_cbor_universal(piece_cid),
            size,
            term_min,
            term_max,
            expiration
        ])

    return cbor2.dumps([
        entries,
        [],
    ])


def _batch_pieces(pieces: list[dict]) -> list[list[tuple[str, int]]]:
    BATCH_SIZE = 500

    return [
        [(p["pieceCid"], int(p["pieceSize"])) for p in pieces[i:i + BATCH_SIZE]]
        for i in range(0, len(pieces), BATCH_SIZE)
    ]
