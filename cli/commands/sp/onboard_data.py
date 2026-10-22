import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import click
import humanfriendly
from hexbytes import HexBytes

from cli import utils
from cli.commands import utils as commands_utils
from cli.services.contracts.evidence_adapter import EvidenceType
from cli.services.contracts.porep_market import PoRepMarket, PoRepMarketDealState
from cli.services.contracts.porep_market_view_helper import PoRepMarketDealView, PoRepMarketViewHelper
from cli.services.contracts.sector_evidence_adapter import SectorEvidenceAdapter
from cli.services.piece_set_commitment import PieceSet
from cli.services.self_update import SelfUpdateService


def _get_aria2c_path() -> str:
    aria2c_path = utils.get_env_required("ARIA2C_PATH", default="aria2c")

    if aria2c_path != "aria2c":
        aria2c_path = Path(aria2c_path).resolve()

    # noinspection PyBroadException
    try:
        subprocess.run([aria2c_path, "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    # pylint: disable=broad-exception-caught
    except Exception as e:
        click.echo("aria2c not found. Please install aria2c to use this command.\n"
                   "See https://aria2.github.io/ and https://github.com/aria2/aria2 for more information.\n"
                   "Set the ARIA2C_PATH environment variable if aria2c is installed but not in PATH.\n"
                   "The easiest installation method is using the terminal:\n"
                   "run sudo apt install aria2 (Debian/Ubuntu), sudo dnf install aria2 (Fedora), or sudo pacman -S aria2 (Arch).\n")

        raise click.ClickException(f"{aria2c_path} not found:\n{e}") from e

    return str(aria2c_path)


def _write_aria2c_input_file(pieces: list[dict], download_host: str, output_dir: Path, no_summary: bool) -> Path:
    with tempfile.NamedTemporaryFile(delete=False) as f:
        aria2_file = Path(f.name)

    pieces_filesize_bytes = sum(piece.get("fileSize", 0) for piece in pieces)
    pieces_piecesize_bytes = sum(piece.get("pieceSize", 0) for piece in pieces)
    click.echo(f"Downloading {len(pieces)} .car files with total fileSize "
               f"{humanfriendly.format_size(pieces_filesize_bytes)} = {humanfriendly.format_size(pieces_filesize_bytes, binary=True)}, "
               f"{utils.bytes_to_sectors(pieces_piecesize_bytes, PoRepMarket().get_sector_size_bytes())} sectors" + (":" if not no_summary else ""))

    with open(aria2_file, "w", encoding="utf-8") as f:
        for piece in pieces:
            storage_path = piece["storagePath"]
            output_file = (output_dir / storage_path).resolve()
            piece_name = storage_path.removesuffix(".car")

            # disallow path traversal outside of the output directory
            if output_dir not in output_file.parents:
                raise click.ClickException(f"Invalid manifest piece storagePath: {storage_path}")

            download_url = f"{download_host}/piece/{piece_name}"

            f.write(f"{download_url}\n")
            f.write(f"  out={output_file.name}\n")
            f.write(f"  dir={output_file.parent}\n")

            if not no_summary:
                click.echo(f"  {download_url} -> {output_file}")

    if not no_summary:
        click.echo("(use --no-summary to skip this summary)")
        click.echo("\n")

    return aria2_file.resolve()


def _write_manifest_file(manifest: list[dict], output_dir: Path, deal_id: int) -> Path:
    click.echo()
    manifest_file = output_dir / f"manifest_{deal_id}.json"

    if manifest_file.exists():
        with open(manifest_file, "r", encoding="utf-8") as f:
            existing_manifest = json.load(f)

        if utils.json_pretty(existing_manifest, True) != utils.json_pretty(manifest, True):
            utils.confirm(f"A different manifest already exists in the output directory: {manifest_file}\n"
                          "Do you want to overwrite it?", abort=True)

    with open(manifest_file, "w", encoding="utf-8") as f:
        f.write(utils.json_pretty(manifest))

    click.echo(f"Deal manifest saved to {manifest_file}\n")
    return manifest_file.resolve()


@click.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("deal_id", type=click.IntRange(min=1))
@click.option("--output-dir", type=click.Path(file_okay=False), required=True,
              help="Directory to save downloaded pieces.")
@click.option("--host",
              help="Host to use for .car files download.  [default: same host as manifest URL]")
@click.option("--port", default=7777, type=click.IntRange(min=1, max=65535), show_default=True,
              help="Port to use for .car files download.")
@click.option("--force", is_flag=True, default=False,
              help="Force download even if all allocations are claimed (sector placement deals: all pieces are placed).  [default: false]")
@click.option("--no-summary", is_flag=True, default=False,
              help="Don't print the initial download summary.  [default: false]")
@click.option("--claim-allocations", type=click.Choice(["curio", "boost"], case_sensitive=False),
              help="Claim allocation(s) for each piece right after download using specified software; DataCap deals only.  [default: none]")
@click.pass_context
# TODO LATER add commP files verification after download
def onboard_data(ctx,
                 deal_id: int,
                 output_dir: str,
                 port: int,
                 host: str | None = None,
                 force: bool = False,
                 no_summary: bool = False,
                 claim_allocations: str | None = None):
    """
    \b
    Download data for a deal using aria2 downloader.

    \b
    Works for both evidence types: DataCap deals skip pieces whose allocations are claimed, sector placement
    deals skip pieces whose placement is accepted (seal the rest with `sp get-piece-notifications`).

    \b
    Unknown [OPTIONS] are passed directly to aria2c, allowing for flexible configuration.
    See aria2c --help for available options.

    DEAL_ID - The ID of the deal to download pieces for.

    \b
    See https://aria2.github.io/ and https://github.com/aria2/aria2 for more information about aria2 and installation instructions.
    """

    SelfUpdateService.check_and_prompt(manual=False)

    aria2c_path = _get_aria2c_path()

    click.echo("Fetching deal details...")
    deal = PoRepMarketViewHelper().get_deal_view(deal_id)

    if deal.deal.state not in (PoRepMarketDealState.ACCEPTED, PoRepMarketDealState.ACTIVE):
        raise click.ClickException(f"Deal ID {deal_id} is in state {deal.deal.state}, expected ACCEPTED or ACTIVE")

    evidence_type = commands_utils.get_evidence_type(deal.deal.evidence_adapter_address)

    if evidence_type == EvidenceType.SECTOR_PLACEMENT:
        if claim_allocations:
            raise click.UsageError(f"Deal ID {deal_id} uses {evidence_type} evidence: it has no DataCap allocations to claim. Seal each piece "
                                   f"with its FIP-0109 notification from `{sys.argv[0]} sp get-piece-notifications {deal_id}` instead.")

        manifest = _fetch_sector_placement_manifest(deal)
        cids_done = _accepted_piece_cids(deal, manifest[0]["pieces"])
        done_label = "placed"

        if len(cids_done) == len(manifest[0]["pieces"]) and not force:
            click.echo(f"All {len(cids_done)} pieces of deal ID {deal_id} are placed; no need to download the data. Use --force to download anyway.")
            return

        click.echo(f"Found {len(manifest[0]['pieces']) - len(cids_done)} pieces not placed and {len(cids_done)} placed for deal ID {deal_id}, "
                   f"{len(manifest[0]['pieces'])} total")

    else:
        deal_allocations = commands_utils.get_deal_allocations(deal.deal)
        deal_claims = commands_utils.get_deal_claims(deal.deal)
        allocations_not_claimed = {allocation_id: alloc for allocation_id, alloc in deal_allocations.items() if str(allocation_id) not in deal_claims}
        cids_done = {claim.get("Data", {}).get("/") for claim in deal_claims.values()}
        done_label = "claimed"

        if deal_claims and not allocations_not_claimed and not force:
            click.echo(f"All {len(deal_claims)} allocations for deal ID {deal_id} are claimed; no need to download the data. Use --force to download anyway.")
            return

        if not deal_claims and not allocations_not_claimed:
            raise click.ClickException(f"No allocations found for deal ID {deal_id} but deal in {deal.deal.state} state.")

        click.echo(f"Found {len(allocations_not_claimed)} allocations not claimed and {len(deal_claims)} claims for deal ID {deal_id}, "
                   f"{len(deal_allocations) + len(deal_claims)} total")

        manifest, _ = commands_utils.fetch_manifest(deal.data.manifest_location, show_manifest=False, retries=10)

    pieces = manifest[0]["pieces"]
    pieces_done = [piece for piece in pieces if piece["pieceCid"] in cids_done]
    pieces_to_download = [piece for piece in pieces if piece not in pieces_done]

    if pieces_done and not force:
        click.echo(f"Skipping download of {len(pieces_done)} already {done_label} pieces. Use --force to download them anyway.")

    _output_dir = Path(output_dir).resolve()
    _output_dir.mkdir(parents=True, exist_ok=True)
    _write_manifest_file(manifest, _output_dir, deal_id)

    if host and not host.startswith(("http://", "https://")):
        host = f"http://{host}"

    parsed_url = commands_utils.validate_and_parse_url(host or deal.data.manifest_location)
    download_host = f"{parsed_url.scheme or 'http'}://{parsed_url.hostname}:{port}"
    aria2_file = _write_aria2c_input_file(pieces_to_download if not force else pieces, download_host, _output_dir, no_summary)

    try:
        command = [aria2c_path,
                   "-i", str(aria2_file),
                   "-x", "16",
                   "-s", "16",
                   "--continue=true",
                   "--auto-file-renaming=false",
                   "--summary-interval=30",
                   "--console-log-level=warn"] + ctx.args

        if claim_allocations:
            callback_path = Path(sys.argv[0]).parent / "cli" / "commands" / "sp" / "_aria2_callback.py"
            command += [f"--on-download-complete={callback_path}"]

            env = {
                **os.environ,
                "ARIA2C_CLAIM_ALLOCATIONS_SOFTWARE": claim_allocations,
                "ARIA2C_DEAL_ID": str(deal_id),
            }
        else:
            env = None  # default argument

        utils.confirm(f"\nRunning command:\n  {' '.join(command)}\nContinue?", default=True, abort=True)
        click.echo("\n")
        subprocess.run(command, check=True, env=env)

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"aria2c failed with exit code {e.returncode}") from e

    finally:
        aria2_file.unlink(missing_ok=True)

    if evidence_type == EvidenceType.SECTOR_PLACEMENT:
        click.echo(f"\nDownloaded. Seal each piece with its FIP-0109 notification: `{sys.argv[0]} sp get-piece-notifications {deal_id} --not-accepted`.")


# A sector placement deal commits to its piece set on-chain: only download pieces of the manifest the deal was proposed with
def _fetch_sector_placement_manifest(deal: PoRepMarketDealView) -> list[dict]:
    manifest, _ = commands_utils.fetch_manifest(deal.data.manifest_location, show_manifest=False, retries=10)
    piece_set = PieceSet(manifest[0]["pieces"])

    if piece_set.commitment() != deal.data.manifest_hash:
        raise click.ClickException(f"Manifest piece-set commitment {piece_set.commitment().to_0x_hex()} does not match deal ID "
                                   f"{deal.deal.deal_id} manifest hash {HexBytes(deal.data.manifest_hash).to_0x_hex()}")

    if piece_set.size_bytes != deal.terms.requested_size_bytes:
        raise click.ClickException(f"Manifest pieces size {piece_set.size_bytes} does not match deal ID {deal.deal.deal_id} "
                                   f"requested size {deal.terms.requested_size_bytes}")

    return manifest


# piece CIDs whose placement the deal's sector evidence adapter has already accepted
def _accepted_piece_cids(deal: PoRepMarketDealView, pieces: list[dict]) -> set[str]:
    evidence_adapter = SectorEvidenceAdapter(deal.deal.evidence_adapter_address)
    return {row.piece_cid for row in PieceSet(pieces).rows if evidence_adapter.is_piece_accepted(deal.deal.deal_id, row.index)}
