from pathlib import Path

import cbor2
import click
import multibase

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.client import _utils as client_utils
from cli.commands.client._client import client_address, client_private_key
from cli.services.contracts.client_contract import ClientContract, TransferParams
from cli.services.contracts.porep_market import PoRepMarket, PoRepMarketDealState
from cli.services.web3_service import Web3Service, ActorId


@click.command()
@click.argument("deal_id", type=click.IntRange(min=0))
@click.option("--print-only", is_flag=True, default=False,
              help="Print transfer params without broadcasting.  [default: false]")
@click.option("--exclude-dag", is_flag=True, default=False,
              help="Exclude manifest DAG piece. Default is to include it.  [default: false]")
@click.option("--local-manifest", type=click.Path(exists=True, dir_okay=False),
              help="Local manifest file to use instead of fetching from the deal proposal.")
def make_allocations(deal_id: int, print_only: bool = False, exclude_dag: bool = False, local_manifest: str | None = None):
    """
    Interactively make DDO allocations for an accepted deal in batches (groups).

    DEAL_ID: ID of the deal to make DDO allocations for.

    \b
    1. Fetch deal proposal and manifest for the given DEAL_ID,
    2. prepare DataCap transfer parameters for each batch of pieces,
    3. make Direct Data Onboarding (DDO) allocation for each batch using Client smart contract,
    4. IMPORTANT: mark deal as completed to allow SP to submit the proof and receive payment.
    """

    # TODO improve click.echo here
    Web3Service().wait_for_pending_transactions(client_address())

    deal = PoRepMarket().get_deal_proposal(deal_id)

    if deal.state != PoRepMarketDealState.ACCEPTED:
        raise click.ClickException(f"Deal ID {deal_id} is in state {deal.state} != ACCEPTED")

    if deal.rail_id == 0:
        raise click.ClickException(f"Deal ID {deal_id} does not have a FileCoinPay rail set")

    if not deal.validator_address:
        raise click.ClickException(f"Deal ID {deal_id} does not have a validator set")

    deal_allocations = commands_utils.get_deal_allocations(deal)
    deal_claims = commands_utils.get_deal_claims(deal)

    click.echo(f"Found {len(deal_allocations)} allocations already made and {len(deal_claims)} claims for deal ID {deal_id}")

    if deal_claims:
        raise RuntimeError("Some allocations claimed but deal still in ACCEPTED state")

    if local_manifest:
        manifest = commands_utils.fetch_local_manifest(Path(local_manifest).resolve())
    else:
        manifest = commands_utils.fetch_manifest(deal.manifest_location, show_manifest=False)

    pieces = manifest[0]["pieces"]

    if exclude_dag:
        pieces = [piece for piece in pieces if piece["pieceType"] != "dag"]

    cids_allocated = [alloc.get("Data", {}).get("/") for alloc in [*deal_allocations.values(), *deal_claims.values()]]
    pieces_not_allocated = [piece for piece in pieces if piece["pieceCid"] not in cids_allocated]
    batches = _batch_pieces(pieces_not_allocated)

    if not pieces_not_allocated:
        raise RuntimeError("All pieces allocated but deal still in ACCEPTED state")

    utils.confirm(f"Continue with allocation of remaining {len(pieces_not_allocated)} pieces in {len(batches)} batches?", default=True, abort=True)

    EPOCHS_IN_MONTH = PoRepMarket().get_epochs_in_month()
    EPOCHS_IN_DAY = EPOCHS_IN_MONTH // 30  # PoRep Market smart contracts assumes month == 30 days
    assert EPOCHS_IN_DAY * 30 == EPOCHS_IN_MONTH

    term_min = deal.terms.duration_days * EPOCHS_IN_DAY
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
            provider_id=deal.provider_id,
            batch=batch,
            term_min=term_min,
            term_max=term_max,
            expiration=Web3Service().get_block_number() + EPOCHS_IN_MONTH
        )

        total_size = sum(size for _, size in batch)

        # noinspection PyArgumentList
        params = TransferParams(
            to=(b"\x00\x06",),
            amount=(utils.uint_to_bytes(utils.to_wei(total_size, utils.DATACAP_DECIMALS), size=None), False),
            operator_data=operator_data
        )

        if print_only:
            click.echo(f"to={params.to[0].hex()}  amount={params.amount[0].hex()}  operator_data={params.operator_data.hex()}")
        else:
            tx_hash = ClientContract().transfer(params, deal_id, client_private_key())
            click.echo(f"params: {params!r}, tx={tx_hash}")

            if tx_hash == Web3Service.ZERO_TX_HASH:
                click.echo("Cannot continue with dry-run mode, exiting.")
                return

            allocation_size = ClientContract().get_size_of_allocations(deal_id)
            click.echo(f"Batch {current_batch_number} done.")
            click.echo(f"Allocated size ({allocation_size}/{deal.terms.deal_size_bytes})")

    if not print_only:
        client_utils.complete_deal(deal)

    click.echo("\nAll done!")


def _build_operator_data_batch(provider_id: ActorId, batch: list[tuple[str, int]], term_min: int, term_max: int, expiration: int) -> bytes:
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
