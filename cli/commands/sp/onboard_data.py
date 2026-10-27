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
from cli.commands.repair_utils import find_healthy_source, get_retrieval_client_path
from cli.commands.sp._repair_download import download_with_lpr
from cli.services.cid_converter import piece_cid_v1_to_v2
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
              help="Host to use for .car files download.  [default: same host as manifest URL; with --downloader lpr: a healthy "
                   "SP found from other providers' deals for the same dataset]")
@click.option("--port", default=7777, type=click.IntRange(min=1, max=65535), show_default=True,
              help="Port to use for .car files download.")
@click.option("--force", is_flag=True, default=False,
              help="Force download even if all DDO pieces are placed.  [default: false]")
@click.option("--no-summary", is_flag=True, default=False,
              help="Don't print the initial download summary.  [default: false]")
@click.option("--downloader", type=click.Choice(["aria2", "lpr"], case_sensitive=False), default="aria2", show_default=True,
              help="aria2 for a free HTTP piece server; lpr for a repair from another SP's large-paid-retrievals sp-proxy, with "
                   "retrieval-client, paid from the deal payee's FileCoinPay account funded by the client (`client pay-repair-retrieval`).")
@click.option("--payee-key-file", envvar="SP_PAYEE_KEY_FILE", show_envvar=True, type=click.Path(exists=True, dir_okay=False),
              help="For paid lpr downloads: file with the private key of the deal's payee address, passed to retrieval-client.  "
                   "[default: FILPAY_PRIVATE_KEY env var]")
@click.option("--allow-unfunded-retrieval", is_flag=True, default=False,
              help="For paid lpr downloads: download even if the client's repair deposits don't cover the retrieval quote, or can't be "
                   "checked; the payee's own funds pay the rest.  [default: false]")
@click.pass_context
# TODO LATER add commP files verification after download
def onboard_data(ctx,
                 deal_id: int,
                 output_dir: str,
                 port: int,
                 host: str | None = None,
                 force: bool = False,
                 no_summary: bool = False,
                 claim_allocations: str | None = None,
                 downloader: str = "aria2",
                 payee_key_file: str | None = None,
                 allow_unfunded_retrieval: bool = False):
    """
    \b
    Download data for a deal using aria2 downloader or, for a repair from another SP's large-paid-retrievals sp-proxy,
    retrieval-client (--downloader lpr): a paid download only starts once the client's deposits into the deal payee's
    FileCoinPay account (`client pay-repair-retrieval`) cover the quote, and a free one needs no payee key.

    \b
    Unknown [OPTIONS] are passed directly to aria2c / retrieval-client fetch, allowing for flexible configuration.
    See aria2c --help / retrieval-client fetch --help for available options.

    DEAL_ID - The ID of the deal to download pieces for.

    \b
    See https://aria2.github.io/ and https://github.com/aria2/aria2 for more information about aria2 and installation instructions.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    aria2c_path = _get_aria2c_path() if downloader == "aria2" else None

    if downloader == "lpr":
        get_retrieval_client_path()  # fail before anything else if retrieval-client is missing

    click.echo("Fetching deal details...")
    deal = PoRepMarketViewHelper().get_deal_view(deal_id)
    manifest, _ = commands_utils.fetch_manifest(deal.data.manifest_location, show_manifest=False, retries=10)
    pieces = manifest[0]["pieces"]

    _validate_deal(deal, manifest)

    evidence_adapter = SectorEvidenceAdapter(deal.deal.evidence_adapter_address)
    cids_done = {row.piece_cid for row in PieceSet(pieces).rows
                 if evidence_adapter.is_piece_accepted(deal.deal.deal_id, row.index)}

    if len(cids_done) == len(pieces) and not force:
        click.echo(f"All {len(cids_done)} pieces of deal ID {deal_id} are placed; no need to download the data. Use --force to download anyway.")
        return

    click.echo(f"Found {len(pieces) - len(cids_done)} pieces not placed and {len(cids_done)} placed for deal ID {deal_id}, "
               f"{len(pieces)} total")

    pieces_done = [piece for piece in pieces if piece["pieceCid"] in cids_done]
    pieces_to_download = [piece for piece in pieces if piece not in pieces_done]

    if pieces_done and not force:
        click.echo(f"Skipping download of {len(pieces_done)} already placed pieces. Use --force to download them anyway.")

    _output_dir = Path(output_dir).resolve()
    _output_dir.mkdir(parents=True, exist_ok=True)
    _write_manifest_file(manifest, _output_dir, deal_id)

    if host and not host.startswith(("http://", "https://")):
        host = f"http://{host}"

    parsed_url = commands_utils.validate_and_parse_url(host or deal.data.manifest_location)
    download_host = f"{parsed_url.scheme or 'http'}://{parsed_url.hostname}:{port}"

    if downloader == "lpr":
        if not host:
            download_host = find_healthy_source(pieces, {deal.deal.provider_id}).base_url

        download_with_lpr(ctx, deal, pieces_to_download if not force else pieces, download_host, _output_dir, no_summary,
                          payee_key_file, allow_unfunded_retrieval)
        _add_piece_cid_v2_names(pieces, _output_dir)
        return

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

    _add_piece_cid_v2_names(pieces, _output_dir)


def _add_piece_cid_v2_names(pieces: list[dict], output_dir: Path):
    linked = _link_piece_cid_v2_names(pieces, output_dir)

    if linked:
        click.echo(f"\nNamed {linked} downloaded piece(s) also by piece CID v2 (<pieceCidV2>.car), as Curio requests the offline data "
                   f"of `client submit-ddo` deals.")


# Files are saved under the manifest storagePath (piece CID v1), but Curio requests the offline data of DDO deals submitted with
# `client submit-ddo` by piece CID v2. Add a <pieceCidV2>.car hard link next to each downloaded piece (a symlink where hard links
# are not supported); existing links are kept, so re-running is safe.
def _link_piece_cid_v2_names(pieces: list[dict], output_dir: Path) -> int:
    linked = 0

    for piece in pieces:
        output_file = (output_dir / piece["storagePath"]).resolve()

        if output_dir not in output_file.parents or not output_file.is_file():
            continue

        v2_file = output_file.with_name(f"{piece_cid_v1_to_v2(piece['pieceCid'], int(piece['fileSize']))}.car")

        if v2_file.exists():
            if not v2_file.samefile(output_file):
                click.echo(f"WARNING: {v2_file} already exists and is not {output_file}; left as is")
            continue

        try:
            os.link(output_file, v2_file)
        except OSError:
            v2_file.symlink_to(output_file.name)

        linked += 1

    return linked


def _validate_deal(deal: PoRepMarketDealView, manifest: list[dict]):
    commands_utils.ensure_deal_evidence_type(deal.deal, EvidenceType.SECTOR_PLACEMENT)

    if deal.deal.state not in (PoRepMarketDealState.ACCEPTED, PoRepMarketDealState.ACTIVE):
        raise click.ClickException(f"Deal ID {deal.deal.deal_id} is in state {deal.deal.state}, expected ACCEPTED or ACTIVE")

    piece_set = PieceSet(manifest[0]["pieces"])

    if piece_set.commitment() != deal.data.manifest_hash:
        raise click.ClickException(f"Manifest piece-set commitment {piece_set.commitment().to_0x_hex()} does not match deal ID "
                                   f"{deal.deal.deal_id} manifest hash {HexBytes(deal.data.manifest_hash).to_0x_hex()}")

    if piece_set.size_bytes != deal.terms.requested_size_bytes:
        raise click.ClickException(f"Manifest pieces size {piece_set.size_bytes} does not match deal ID {deal.deal.deal_id} "
                                   f"requested size {deal.terms.requested_size_bytes}")
