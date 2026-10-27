import click

from cli.commands import utils as commands_utils
from cli.commands.client._client import client_signer
from cli.services.cid_converter import piece_cid_v1_to_v2
from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper
from cli.services.curio_market_client import CurioMarketDiscovery, find_curio_market_endpoint, piece_identifier


@click.command("ddo-status")
@click.argument("deal_id", type=click.IntRange(min=1))
@click.option("--curio-url",
              help="Override Curio Market endpoint discovery. Intended for development/debugging.")
def ddo_status(deal_id: int, curio_url: str | None = None):
    """
    Print Curio DDO statuses for all pieces of a PoRep Market deal.

    \b
    DEAL_ID - PoRep Market deal ID.
    """

    deal = PoRepMarketViewHelper().get_deal_view(deal_id)
    manifest, _ = commands_utils.fetch_manifest(deal.data.manifest_location, show_manifest=False, quiet=True, retries=10)

    _curio_url = [curio_url] if curio_url else CurioMarketDiscovery.get_market_urls(deal.deal.provider_id)
    curio = find_curio_market_endpoint(client_signer(), _curio_url, market_address=None)
    total_pieces = len(manifest[0]["pieces"])

    click.echo(f"Deal ID: {deal_id}\n"
               f"Storage Provider: {deal.deal.provider_id}\n"
               f"Curio endpoint: {curio.base_url}\n")

    for index, piece in enumerate(manifest[0]["pieces"], start=1):
        piece_cid_v2 = piece_cid_v1_to_v2(piece["pieceCid"], piece["fileSize"])
        identifier = piece_identifier(deal_id, piece_cid_v2, client_signer())

        status_result = curio.get_deal_status_or_none(identifier)
        ddo_status = (status_result.get("ddo_v1") or {}) if status_result else None
        status = (ddo_status.get("status") or "unknown") if ddo_status else "not found / unauthorized"
        error = ddo_status.get("errorMsg") if ddo_status else None

        message = (f"[{index}/{total_pieces}] "
                   f"CIDv1: {piece['pieceCid']} -> CIDv2: {piece_cid_v2} ({identifier}): {status.lower()}")

        if error:
            message += f" - {error}"

        click.echo(message)
