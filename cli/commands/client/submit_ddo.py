import sys
from pathlib import Path

import click
from hexbytes import HexBytes

from cli import utils
from cli._cli import is_dry_run
from cli.commands import utils as commands_utils
from cli.commands.client._client import client_signer, client_address
from cli.services.cid_converter import piece_cid_v1_to_v2, padded_piece_size_for_payload
from cli.services.contracts.evidence_adapter import EvidenceType
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.porep_market import (
    PoRepMarketDealState,
    PoRepMarketDealType,
)
from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper, PoRepMarketDealView
from cli.services.contracts.sector_evidence_adapter import SectorEvidenceAdapter
from cli.services.curio_market_client import (
    CurioMarketDiscovery,
    find_curio_market_endpoint,
    piece_identifier,
)
from cli.services.piece_set_commitment import PieceSet
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import EthAddress, FilAddress


@click.command("submit-ddo")
@click.argument("deal_id", type=click.IntRange(min=1))
@click.option("--local-manifest", type=click.Path(exists=True, dir_okay=False),
              help="Local manifest file to use instead of fetching from the deal proposal.")
@click.option("--curio-url",
              help="Override Curio Market endpoint discovery. Intended for development/debugging.")
@click.option("--print-only", is_flag=True, default=False,
              help="Print DDO submissions without sending them to Curio.")
@click.option("--skip-preflight", is_flag=True, default=False,
              help="Skip Curio preflight checks. Intended for development/debugging.")
@click.option("--source-url",
              help="Base URL of an HTTP piece server holding the data (e.g. another SP's https://host:port): Curio downloads each piece "
                   "from <url>/piece/<pieceCid> itself.  [default: offline, the SP imports the data, see `sp onboard-data`]")
def submit_ddo(deal_id: int,
               local_manifest: str | None = None,
               curio_url: str | None = None,
               print_only: bool = False,
               skip_preflight: bool = False,
               source_url: str | None = None):
    """
    Submit PoRep Market deal pieces to the Storage Provider through Curio Market 2.0.

    Each manifest piece is submitted as a DDO deal with the same
    FIP-0109 notification payload produced by `sp get-piece-notifications`.
    The data is offline (the SP imports it) unless --source-url is given.

    \b
    DEAL_ID - PoRep Market deal ID.
    """

    SelfUpdateService.check_and_prompt(manual=False)

    if is_dry_run() and not print_only:
        click.echo("Dry-run mode: acting as --print-only")
        print_only = True

    deal = PoRepMarketViewHelper().get_deal_view(deal_id)
    _validate_deal(deal)

    if source_url:
        # the SP's Curio fetches this URL: same private-address guard as for manifests
        source_url = source_url.rstrip("/")
        commands_utils.validate_and_parse_url(source_url)

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

    # Not using CurioDealViewV1 flow.
    market_address = None
    market_deal_id = None

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

        file_size = int(manifest_piece["fileSize"])
        implied_piece_size = padded_piece_size_for_payload(file_size)

        if implied_piece_size != row.padded_size:
            raise click.ClickException(
                f"Piece {row.piece_cid}: fileSize {file_size} implies "
                f"piece size {implied_piece_size}, but manifest pieceSize "
                f"is {row.padded_size}"
            )

        piece_cid_v2 = piece_cid_v1_to_v2(row.piece_cid, int(manifest_piece["fileSize"]))
        notification_payload = bytes(piece_set.notification_payload(deal_id, row.index))
        identifier = piece_identifier(deal_id, piece_cid_v2, client_signer())

        pieces_to_submit.append({
            "row": row,
            "pieceCidV2": piece_cid_v2,
            "identifier": identifier,
            "notificationPayload": notification_payload,
            "sourceUrl": f"{source_url}/piece/{row.piece_cid}" if source_url else None,
        })

    click.echo(f"Deal ID {deal_id}: "
               f"{len(piece_set.rows)} total piece(s), "
               f"{len(pieces_to_submit)} not accepted yet.")

    if not pieces_to_submit:
        click.echo("All pieces are already accepted.")
        return

    if print_only:
        _print_plan(deal, pieces_to_submit, notification_address, market_address)
        return

    _curio_url = [curio_url] if curio_url else CurioMarketDiscovery.get_market_urls(deal.deal.provider_id)
    curio = find_curio_market_endpoint(client_signer(), _curio_url, market_address, skip_preflight, "http" if source_url else "offline")

    click.echo(f"Storage Provider: {deal.deal.provider_id}\n"
               f"Curio endpoint: {curio.base_url}\n"
               f"Market address: {market_address}\n"
               f"Notification address: {notification_address}\n"
               f"Data source: {source_url + '/piece/<pieceCid>' if source_url else 'offline (the SP imports the data)'}")

    utils.confirm(f"Submit {len(pieces_to_submit)} DDO deal(s) to "
                  f"{deal.deal.provider_id}?",
                  default=True,
                  abort=True)

    submitted = 0
    already_submitted = 0

    for index, piece in enumerate(pieces_to_submit, start=1):
        identifier = piece["identifier"]
        row = piece["row"]

        # TODO LATER
        # Deterministic identifier makes the command safe to rerun.
        # Although it might cause problems when trying to submit failed deal with the same identifier
        existing_deal = curio.get_deal_status_or_none(identifier)

        if existing_deal is not None:
            ddo_status = existing_deal.get("ddo_v1") or {}
            status = ddo_status.get("status")
            error = ddo_status.get("errorMsg")

            if status == "failed":
                raise click.ClickException(f"DDO deal {identifier} for piece {row.piece_cid} "
                                           f"already exists in Curio but failed: {error or 'unknown error'}.")

            if not ddo_status or not status:
                raise click.ClickException(f"Unexpected Curio status response for DDO deal {identifier}: {existing_deal}")

            click.echo(f"[{index}/{len(pieces_to_submit)}] "
                       f"{row.piece_cid}: already submitted "
                       f"({identifier}, status: {status})")

            already_submitted += 1
            continue

        curio.submit_ddo(
            provider=deal.deal.provider_id,
            piece_cid_v2=piece["pieceCidV2"],
            duration_epochs=deal.terms.duration_epochs,

            market_address=market_address,
            market_deal_id=market_deal_id,

            notification_address=notification_address,
            notification_payload=piece["notificationPayload"],

            identifier=identifier,

            indexing=True,
            announce_payload=(deal.deal.deal_type == PoRepMarketDealType.PUBLIC),

            http_urls=[piece["sourceUrl"]] if piece["sourceUrl"] else None,
        )

        click.echo(f"[{index}/{len(pieces_to_submit)}] "
                   f"{row.piece_cid} -> "
                   f"{piece['pieceCidV2']} submitted "
                   f"({identifier})")

        submitted += 1

    click.echo(f"\nDone. "
               f"Submitted: {submitted}, "
               f"already submitted: {already_submitted}.\n"
               + (f"Curio downloads the data from {source_url} itself; the SP does not need to run `sp onboard-data`.\n" if source_url else "")
               + f"Run `{sys.argv[0]} client ddo-status {deal_id}` to check the status of the submitted DDO deals.\n"
               f"All done! Run `{sys.argv[0]} client deposit-for-deals {deal_id}` to deposit funds for this deal.")


def _validate_deal(deal: PoRepMarketDealView):
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
                                                            deal.deal.client_address,
                                                            deal.deal.validator_address)

    if not operator_approval.is_approved:
        raise click.ClickException(f"Deal ID {deal.deal.deal_id} operator is not approved; "
                                   f"run `{sys.argv[0]} client init-deal {deal.deal.deal_id}` first.")

    commands_utils.ensure_deal_evidence_type(deal.deal, EvidenceType.SECTOR_PLACEMENT)


def _print_plan(deal: PoRepMarketDealView,
                pieces: list[dict],
                notification_address: FilAddress | None,
                market_address: EthAddress | None):
    #
    click.echo(utils.json_pretty({
        "dealId": deal.deal.deal_id,
        "providerId": deal.deal.provider_id,
        "marketAddress": market_address,
        "notificationAddress": notification_address,
        "pieces": [
            {
                "pieceCid": piece["row"].piece_cid,
                "pieceCidV2": piece["pieceCidV2"],
                "pieceSize": piece["row"].padded_size,
                "pieceIndex": piece["row"].index,
                "identifier": piece["identifier"],
                "notificationPayload": HexBytes(piece["notificationPayload"]).to_0x_hex(),
                **({"sourceUrl": piece["sourceUrl"]} if piece["sourceUrl"] else {}),
            }
            for piece in pieces
        ]
    }))
