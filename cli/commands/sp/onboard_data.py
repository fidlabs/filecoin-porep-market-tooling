import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.services.contracts.porep_market import PoRepMarket, PoRepMarketDealState


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


def _write_aria2c_input_file(manifest: list[dict], download_host: str, output_dir: Path, no_summary: bool) -> Path:
    with tempfile.NamedTemporaryFile(delete=False) as f:
        aria2_file = Path(f.name)

    pieces = manifest[0]["pieces"]

    click.echo(f"\nDownloading {len(pieces)} .car files" + (":" if not no_summary else ""))

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
        click.echo("\n")

    return aria2_file.resolve()


def _write_manifest_file(manifest: list[dict], output_dir: Path, deal_id: int) -> Path:
    manifest_file = output_dir / f"manifest_{deal_id}.json"

    if manifest_file.exists():
        with open(manifest_file, "r", encoding="utf-8") as f:
            existing_manifest = json.load(f)

        if utils.json_pretty(existing_manifest, True) != utils.json_pretty(manifest, True):
            utils.confirm(f"A different manifest already exists in the output directory: {manifest_file}\n"
                          "Do you want to overwrite it?", abort=True)

    with open(manifest_file, "w", encoding="utf-8") as f:
        f.write(utils.json_pretty(manifest))

    return manifest_file.resolve()

def _get_sptool_path() -> str:
    sptool_path = utils.get_env_required("SPTOOL_PATH", default="sptool")

    if sptool_path != "sptool":
        sptool_path = Path(sptool_path).resolve()

    # noinspection PyBroadException
    try:
        subprocess.run([sptool_path, "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    # pylint: disable=broad-exception-caught
    except Exception as e:
        click.echo("sptool not found. Please install sptool to use this command.\n"
                   "See https://docs.curiostorage.org/installation for more information.\n"
                   "Set the SPTOOL_PATH environment variable if sptool is installed but not in PATH.\n")

        raise click.ClickException(f"{sptool_path} not found:\n{e}") from e

    return str(sptool_path)

def _parse_commp_output(output: str) -> dict:
    fields = {}

    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip().replace(" ", "_").lower()] = value.strip()

    return fields


@click.command(context_settings=dict(ignore_unknown_options=True, allow_extra_args=True))
@click.argument("deal_id", type=click.IntRange(min=0))
@click.option("--output-dir", type=click.Path(file_okay=False), required=True,
              help="Directory to save downloaded pieces.")
@click.option("--host",
              help="Host to use for .car files download.  [default: same host as manifest URL]")
@click.option("--port", default=7777, type=click.IntRange(min=1, max=65535), show_default=True,
              help="Port to use for .car files download.")
@click.option("--force", is_flag=True, default=False,
              help="Force download even if all allocations are claimed.  [default: false]")
@click.option("--no-summary", is_flag=True, default=False,
              help="Don't print the initial download summary.  [default: false]")
@click.option("--claim-allocations", type=click.Choice(["curio", "boost"], case_sensitive=False),
              help="Claim allocation(s) for each piece right after download using specified software.  [default: none]")
@click.pass_context
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
    Unknown [OPTIONS] are passed directly to aria2c, allowing for flexible configuration.
    See aria2c --help for available options.

    DEAL_ID - The ID of the deal to download pieces for.

    \b
    See https://aria2.github.io/ and https://github.com/aria2/aria2 for more information about aria2 and installation instructions.
    """

    aria2c_path = _get_aria2c_path()
    sptool_path = _get_sptool_path()

    click.echo("Fetching deal details...")
    deal = PoRepMarket().get_deal_proposal(deal_id)

    if deal.state != PoRepMarketDealState.COMPLETED:
        raise click.ClickException(f"Deal ID {deal_id} is in state {deal.state} != COMPLETED")

    deal_allocations = commands_utils.get_deal_allocations(deal)
    deal_claims = commands_utils.get_deal_claims(deal)
    allocations_not_claimed = {allocation_id: alloc for allocation_id, alloc in deal_allocations.items() if str(allocation_id) not in deal_claims}

    if deal_claims and not allocations_not_claimed and not force:
        click.echo(f"All {len(deal_claims)} allocations for deal ID {deal_id} are claimed; no need to download the data. Use --force to download anyway.")
        return

    manifest = commands_utils.fetch_manifest(deal.manifest_location, show_manifest=False, retries=10)

    _output_dir = Path(output_dir).resolve()
    _output_dir.mkdir(parents=True, exist_ok=True)
    _write_manifest_file(manifest, _output_dir, deal_id)

    if host and not host.startswith(("http://", "https://")):
        host = f"http://{host}"

    parsed_url = commands_utils.validate_and_parse_url(host or deal.manifest_location)
    download_host = f"{parsed_url.scheme or 'http'}://{parsed_url.hostname}:{port}"
    aria2_file = _write_aria2c_input_file(manifest, download_host, _output_dir, no_summary)

    try:
        command = [aria2c_path,
                   "-i", str(aria2_file),
                   "-x", "4",
                   "-s", "4",
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

        click.echo("\nVerifying commP of downloaded pieces:")
        _verify_pieces(manifest, _output_dir, sptool_path)

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"aria2c failed with exit code {e.returncode}") from e

    finally:
        aria2_file.unlink(missing_ok=True)


@click.command()
@click.option("--pieces-dir", type=click.Path(exists=True, file_okay=False), required=True,
              help="Directory containing the downloaded pieces and their manifest.")
def verify_commp(pieces_dir: str) -> None:
    """
    Verify the commP of downloaded pieces against their manifest.

    Expects manifest.json (or the manifest_<dealId>.json written by onboard-data)
    to be in the pieces directory.
    """
    sptool_path = _get_sptool_path()
    _pieces_dir = Path(pieces_dir).resolve()

    with open(_find_manifest_file(_pieces_dir), "r", encoding="utf-8") as f:
        manifest = json.load(f)

    car_files = {path.name for path in _pieces_dir.glob("*.car")}
    expected_car_files = {piece["storagePath"] for piece in manifest[0]["pieces"]}

    if car_files != expected_car_files:
        raise click.ClickException(
            f"CAR files in pieces directory do not match manifest: "
            f"missing={sorted(expected_car_files - car_files)}, extra={sorted(car_files - expected_car_files)}"
        )

    _verify_pieces(manifest, _pieces_dir, sptool_path)


def _find_manifest_file(pieces_dir: Path) -> Path:
    manifest_file = pieces_dir / "manifest.json"
    if manifest_file.exists():
        return manifest_file

    candidates = sorted(pieces_dir.glob("manifest_*.json"))
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise click.ClickException(f"Multiple manifest files found in {pieces_dir}: {[c.name for c in candidates]}")

    raise click.ClickException(f"Manifest file not found in {pieces_dir} (expected manifest.json or manifest_<dealId>.json)")


def _verify_pieces(manifest: list[dict], pieces_dir: Path, sptool_path: str) -> None:
    pieces = manifest[0]["pieces"]
    failed = 0

    for piece in pieces:
        car_path = (pieces_dir / piece["storagePath"]).resolve()

        if not car_path.is_file():
            click.secho(f"x {car_path}", fg="yellow")
            _format_commp_warnings(["File not found"])
            failed += 1
            continue

        command = [sptool_path, "--actor", "any", "toolbox", "mk12-client", "commp", str(car_path)]
        try:
            output = subprocess.run(command, check=True, capture_output=True, text=True).stdout
        except subprocess.CalledProcessError as e:
            raise click.ClickException(f"Failed to compute commP for {car_path}:\n{e.stderr}") from e

        warnings = _get_commp_warnings(_parse_commp_output(output), piece)

        if warnings:
            click.secho(f"x {car_path}", fg="yellow")
            _format_commp_warnings(warnings)
            failed += 1
        else:
            click.secho(f"✓ {car_path}", fg="green")

    click.echo()

    if failed:
        raise click.ClickException(f"commP verification failed for {failed} of {len(pieces)} piece(s)")

    click.secho(f"Verified all {len(pieces)} piece(s).", fg="green")

def _get_commp_warnings(result: dict, piece: dict) -> list[str]:
    warnings = []
    if result["commp_cid"] != piece["pieceCid"]:
        warnings.append(f"CommP CID mismatch: {result['commp_cid']} != {piece['pieceCid']}")
    if int(result["piece_size"]) != piece["pieceSize"]:
        warnings.append(f"Piece size mismatch: {result['piece_size']} != {piece['pieceSize']}")
    if int(result["car_file_size"]) != piece["fileSize"]:
        warnings.append(f"Car file size mismatch: {result['car_file_size']} != {piece['fileSize']}")
    return warnings

def _format_commp_warnings(warnings: list[str]) -> None:
    for i, warning in enumerate(warnings):
        prefix = "└──" if i == len(warnings) - 1 else "├──"
        click.secho(f"  {prefix} {warning}", fg="yellow")
