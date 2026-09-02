import click
import humanfriendly

from cli import utils
from cli.commands.utils import fetch_manifest
from cli.services.contracts.porep_market import PoRepMarket


@click.command()
@click.argument("manifest_url")
def validate_manifest(manifest_url: str):
    """
    Validate a manifest file for correctness and completeness.

    \b
    MANIFEST_URL - URL of the deal manifest file to validate.
    """

    manifest, _ = fetch_manifest(manifest_url)

    SECTOR_SIZE_BYTES = PoRepMarket().get_sector_size_bytes()
    pieces = manifest[0]["pieces"]
    pieces_size_bytes = sum(piece.get("pieceSize", 0) for piece in pieces)

    click.echo(f"\nFound {len(pieces)} total pieces with total pieceSize "
               f"{humanfriendly.format_size(pieces_size_bytes)} = {humanfriendly.format_size(pieces_size_bytes, binary=True)} = "
               f"{utils.bytes_to_sectors(pieces_size_bytes, SECTOR_SIZE_BYTES)} sectors "
               f"(including dag piece)")

    click.echo("Manifest valid")
