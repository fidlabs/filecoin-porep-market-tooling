from pathlib import Path

import click
from hexbytes import HexBytes

from cli import utils
from cli.commands import utils as commands_utils
from cli.services.contracts.evidence_adapter import EvidenceType
from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper
from cli.services.contracts.sector_evidence_adapter import SectorEvidenceAdapter
from cli.services.piece_set_commitment import PieceSet


@click.command()
@click.argument("deal_id", type=click.IntRange(min=1))
@click.option("--not-accepted", is_flag=True, default=False,
              help="Show only pieces whose placement has not been accepted yet.  [default: false]")
@click.option("--local-manifest", type=click.Path(exists=True, dir_okay=False),
              help="Local manifest file to use instead of fetching from the deal proposal.")
def get_piece_notifications(deal_id: int, not_accepted: bool = False, local_manifest: str | None = None):
    """
    \b
    Get FIP-0109 sector content notifications for a sector evidence deal.

    \b
    Each deal piece must be sealed with a notification sent to the deal's evidence adapter address with given payload.
    ProveCommit or replica-update call must set `require_notification_success` to true.

    \b
    DEAL_ID - The ID of the deal to get piece notifications for.
    """

    deal = PoRepMarketViewHelper().get_deal_view(deal_id)
    commands_utils.ensure_deal_evidence_type(deal.deal, EvidenceType.SECTOR_PLACEMENT)

    if local_manifest:
        manifest, _ = commands_utils.fetch_local_manifest(Path(local_manifest).resolve(), quiet=True)
    else:
        manifest, _ = commands_utils.fetch_manifest(deal.data.manifest_location, show_manifest=False, quiet=True, retries=10)

    piece_set = PieceSet(manifest[0]["pieces"])

    if piece_set.commitment() != deal.data.manifest_hash:
        raise click.ClickException(f"Manifest piece-set commitment {piece_set.commitment().to_0x_hex()} does not match "
                                   f"deal ID {deal_id} manifest hash {HexBytes(deal.data.manifest_hash).to_0x_hex()}")

    if piece_set.size_bytes != deal.terms.requested_size_bytes:
        raise click.ClickException(f"Manifest pieces size {piece_set.size_bytes} does not match "
                                   f"deal ID {deal_id} requested size {deal.terms.requested_size_bytes}")

    evidence_adapter = SectorEvidenceAdapter(deal.deal.evidence_adapter_address)
    pieces = []

    for row in piece_set.rows:
        accepted = evidence_adapter.is_piece_accepted(deal_id, row.index)

        if not_accepted and accepted:
            continue

        pieces.append({
            "pieceCid": row.piece_cid,
            "pieceSize": row.padded_size,
            "pieceIndex": row.index,
            "accepted": accepted,
            "payload": piece_set.notification_payload(deal_id, row.index).to_0x_hex()
        })

    click.echo(utils.json_pretty({
        "dealId": deal_id,
        "providerId": deal.deal.provider_id,
        "notificationAddress": deal.deal.evidence_adapter_address.to_filecoin_address(),
        "manifestReceipt": evidence_adapter.get_manifest_receipt(deal_id),
        "pieces": pieces
    }))
