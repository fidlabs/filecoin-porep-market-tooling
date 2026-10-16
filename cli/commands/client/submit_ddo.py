import sys
from pathlib import Path

import click
from hexbytes import HexBytes

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.client._client import client_address, client_signer
from cli.services.cid_converter import piece_cid_v1_to_v2
from cli.services.contracts.evidence_adapter import EvidenceType
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.porep_market import (
    PoRepMarketDealState,
    PoRepMarketDealType,
)
from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper
from cli.services.contracts.sector_evidence_adapter import SectorEvidenceAdapter
from cli.services.curio_market_client import (
    CurioMarketClient,
    CurioMarketError, CurioMarketDiscovery,
)
from cli.services.piece_set_commitment import PieceSet
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import Web3Service


@click.command("submit-ddo")
@click.argument("deal_id", type=click.IntRange(min=1))
@click.option("--local-manifest", type=click.Path(exists=True, dir_okay=False),
              help="Local manifest file to use instead of fetching from the deal proposal.")
@click.option("--curio-url",
              help="Override Curio Market endpoint discovery. Intended for development/debugging.")
@click.option("--print-only", is_flag=True, default=False,
              help="Print DDO submissions without sending them to Curio.")
def submit_ddo(deal_id: int,
               local_manifest: str | None = None,
               curio_url: str | None = None,
               print_only: bool = False):
    """
    Submit PoRep Market deal pieces to the Storage Provider through Curio Market 2.0.

    Each manifest piece is submitted as an offline DDO deal with the same
    FIP-0109 notification payload produced by `sp get-piece-notifications`.

    \b
    DEAL_ID - PoRep Market deal ID.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    deal = PoRepMarketViewHelper().get_deal_view(deal_id)

    _validate_deal(deal)

    if local_manifest:
        manifest, _ = commands_utils.fetch_local_manifest(Path(local_manifest).resolve(), quiet=True)
    else:
        manifest, _ = commands_utils.fetch_manifest(deal.data.manifest_location, show_manifest=False, quiet=True, retries=10)

    # IMPORTANT:
    # This is exactly the same PieceSet construction used by
    # sp get-piece-notifications.
    piece_set = PieceSet(manifest[0]["pieces"])

    if piece_set.commitment() != deal.data.manifest_hash:
        raise click.ClickException(f"Manifest piece-set commitment "
                                   f"{piece_set.commitment().to_0x_hex()} does not match "
                                   f"deal ID {deal_id} manifest hash "
                                   f"{HexBytes(deal.data.manifest_hash).to_0x_hex()}")

    if piece_set.size_bytes != deal.terms.requested_size_bytes:
        raise click.ClickException(f"Manifest pieces size {piece_set.size_bytes} does not match "
                                   f"deal ID {deal_id} requested size "
                                   f"{deal.terms.requested_size_bytes}")

    # We still need fileSize from the original manifest to generate PCIDv2.
    # PieceSetRow intentionally only contains canonical PoRep commitment data.
    manifest_pieces = {
        (piece["pieceCid"], int(piece["pieceSize"])): piece
        for piece in manifest[0]["pieces"]
    }

    # TODO ASAP
    # For now the SectorEvidenceAdapter is also the intended Curio market
    # verification contract.
    #
    # Once/if CurioDealViewV1 lives at a separate address, this is the only
    # assignment that needs to change.
    market_address = deal.deal.evidence_adapter_address

    evidence_adapter = SectorEvidenceAdapter(deal.deal.evidence_adapter_address)
    notification_address = deal.deal.evidence_adapter_address.to_filecoin_address()

    pieces_to_submit = []

    for row in piece_set.rows:
        # Same semantics as get-piece-notifications -- already accepted pieces no longer need a DDO submission.

        if evidence_adapter.is_piece_accepted(deal_id, row.index):
            continue

        manifest_piece = manifest_pieces.get((row.piece_cid, row.padded_size))

        if manifest_piece is None:
            raise click.ClickException(f"Cannot find manifest metadata for canonical piece "
                                       f"{row.piece_cid} with size {row.padded_size}")

        piece_cid_v2 = piece_cid_v1_to_v2(row.piece_cid,
                                          int(manifest_piece["fileSize"]))

        notification_payload = bytes(piece_set.notification_payload(deal_id, row.index))

        identifier = _piece_identifier(deal_id=deal_id,
                                       market_address=market_address,
                                       piece_cid_v2=piece_cid_v2)

        pieces_to_submit.append({
            "row": row,
            "pieceCidV2": piece_cid_v2,
            "identifier": identifier,
            "notificationPayload": notification_payload,
        })

    click.echo(f"Deal ID {deal_id}: "
               f"{len(piece_set.rows)} total piece(s), "
               f"{len(pieces_to_submit)} not accepted yet.")

    if not pieces_to_submit:
        click.echo("All pieces are already accepted.")
        return

    if print_only:
        _print_plan(deal_id, deal, pieces_to_submit, notification_address, market_address)
        return

    _curio_url = [curio_url] if curio_url else CurioMarketDiscovery.get_market_urls(deal.deal.provider_id)

    curio = _find_curio_market_endpoint(
        _curio_url,
        client_signer(),
        market_address,
    )

    click.echo(f"Provider: {deal.deal.provider_id}\n"
               f"Curio endpoint: {curio.base_url}\n"
               f"Market address: {market_address}\n"
               f"Notification address: {notification_address}")

    utils.confirm(f"Submit {len(pieces_to_submit)} DDO deal(s) to "
                  f"{deal.deal.provider_id}?",
                  default=True,
                  abort=True)

    submitted = 0
    already_submitted = 0

    for index, piece in enumerate(pieces_to_submit, start=1):
        identifier = piece["identifier"]
        row = piece["row"]

        # TODO ASAP
        # Deterministic identifier makes the command safe to rerun.
        # Although it might cause problems when trying to cubmit failed deal with the same identifier
        existing_deal = curio.get_deal_status_or_none(identifier)

        if existing_deal is not None:
            ddo_status = existing_deal.get("ddo_v1") or {}
            status = ddo_status.get("status")
            error = ddo_status.get("errorMsg")

            if status == "failed":
                raise click.ClickException(f"DDO deal {identifier} for piece {row.piece_cid} "
                                           f"already exists in Curio but failed: {error or 'unknown error'}.")

            click.echo(f"[{index}/{len(pieces_to_submit)}] "
                       f"{row.piece_cid}: already submitted "
                       f"({identifier}, status: {status})")

            already_submitted += 1
            continue

        curio.submit_offline_ddo(
            provider=deal.deal.provider_id,
            piece_cid_v2=piece["pieceCidV2"],
            duration_epochs=deal.terms.duration_epochs,

            market_address=market_address,
            market_deal_id=deal_id,

            notification_address=notification_address,
            notification_payload=piece["notificationPayload"],

            identifier=identifier,

            indexing=True,
            announce_payload=(deal.deal.deal_type == PoRepMarketDealType.PUBLIC),
        )

        click.echo(f"[{index}/{len(pieces_to_submit)}] "
                   f"{row.piece_cid} -> "
                   f"{piece['pieceCidV2']} submitted "
                   f"({identifier})")

        submitted += 1

    click.echo(f"\nDone. "
               f"Submitted: {submitted}, "
               f"already submitted: {already_submitted}.")


def _validate_deal(deal):
    if deal.deal.client_address != client_address():
        raise click.ClickException(f"Deal ID {deal.deal.deal_id} belongs to client "
                                   f"{deal.deal.client_address}, not connected client "
                                   f"{client_address()}.")

    if deal.deal.state != PoRepMarketDealState.ACCEPTED:
        raise click.ClickException(f"Deal ID {deal.deal.deal_id} is in state {deal.deal.state} != ACCEPTED")

    if deal.deal.rail_id == 0:
        raise click.ClickException(f"Deal ID {deal.deal.deal_id} does not have a FileCoinPay rail set; "
                                   f"run `{sys.argv[0]} client init-deal {deal.deal.deal_id}` first.")

    if not deal.deal.validator_address:
        raise click.ClickException(f"Deal ID {deal.deal.deal_id} does not have a validator set; "
                                   f"run `{sys.argv[0]} client init-deal {deal.deal.deal_id}` first.")

    operator_approval = FileCoinPay().get_operator_approval(deal.payment.payment_token,
                                                            client_address(),
                                                            deal.deal.validator_address)

    if not operator_approval.is_approved:
        raise click.ClickException(f"Deal ID {deal.deal.deal_id} operator is not approved; "
                                   f"run `{sys.argv[0]} client init-deal {deal.deal.deal_id}` first.")

    commands_utils.ensure_deal_evidence_type(deal.deal, EvidenceType.SECTOR_PLACEMENT)


def _find_curio_market_endpoint(urls: list[str], signer, market_address) -> CurioMarketClient:
    errors = []

    for url in urls:
        try:
            client = CurioMarketClient(url, signer)
            client.preflight(market_address)

            return client

        except CurioMarketError as e:
            errors.append(f"{url}: {e}")

    raise click.ClickException("No usable Curio Market endpoint found:\n"
                               + "\n".join(errors))


def _piece_identifier(deal_id: int, market_address, piece_cid_v2: str) -> str:
    seed = (
        f"{Web3Service().get_chain_id()}:"
        f"{str(market_address).lower()}:"
        f"{deal_id}:"
        f"{piece_cid_v2}"
    ).encode()

    return CurioMarketClient.deterministic_ulid(seed)


def _print_plan(deal_id,
                deal,
                pieces,
                notification_address,
                market_address):
    #
    output = {
        "dealId": deal_id,
        "providerId": deal.deal.provider_id,
        "marketAddress": market_address,
        "notificationAddress": notification_address,
        "pieces": [],
    }

    for piece in pieces:
        row = piece["row"]

        output["pieces"].append({
            "pieceCid": row.piece_cid,
            "pieceCidV2": piece["pieceCidV2"],
            "pieceSize": row.padded_size,
            "pieceIndex": row.index,
            "identifier": piece["identifier"],
            "notificationPayload": HexBytes(piece["notificationPayload"]).to_0x_hex(),
        })

    click.echo(utils.json_pretty(output))
