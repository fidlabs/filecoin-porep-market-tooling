import json
import subprocess
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


def _write_aria2c_input_file(manifest: list[dict], download_host: str, output_dir: Path) -> Path:
    with tempfile.NamedTemporaryFile(delete=False) as f:
        aria2_file = Path(f.name)

    pieces = manifest[0]["pieces"]

    click.echo(f"\nDownloading {len(pieces)} .car files:\n")

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

            click.echo(f"  {download_url} -> {output_file}")

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


@click.command(context_settings=dict(ignore_unknown_options=True, allow_extra_args=True))
@click.argument("deal_id", type=click.IntRange(min=0))
@click.option("--output-dir", type=click.Path(file_okay=False), required=True, help="Directory to save downloaded pieces.")
@click.option("--host", help="Host to use for .car files download.  [default: same host as manifest URL]")
@click.option("--port", default=7777, type=click.IntRange(min=1, max=65535), show_default=True,
              help="Port to use for .car files download.")
@click.pass_context
# TODO add commP files verification after download
def onboard_data(ctx, deal_id: int, output_dir: str, port: int, host: str | None = None):
    """
    \b
    Download data for a deal using aria2 downloader.

    \b
    Unknown [OPTIONS] are passed directly to aria2c, allowing for flexible configuration.
    See aria2c --help for available options.

    DEAL_ID - ID of the deal to download pieces for.

    \b
    See https://aria2.github.io/ and https://github.com/aria2/aria2 for more information about aria2 and installation instructions.
    """

    aria2c_path = _get_aria2c_path()
    deal = PoRepMarket().get_deal_proposal(deal_id)

    if deal.state != PoRepMarketDealState.COMPLETED:
        raise click.ClickException(f"Deal id {deal_id} is not in COMPLETED state")

    manifest = commands_utils.fetch_manifest(deal.manifest_location, show_manifest=False, retries=10)

    _output_dir = Path(output_dir).resolve()
    _output_dir.mkdir(parents=True, exist_ok=True)
    _write_manifest_file(manifest, _output_dir, deal_id)

    if host and not host.startswith(("http://", "https://")):
        host = f"http://{host}"

    parsed_url = commands_utils.validate_and_parse_url(host or deal.manifest_location)
    download_host = f"{parsed_url.scheme or 'http'}://{parsed_url.hostname}:{port}"
    aria2_file = _write_aria2c_input_file(manifest, download_host, _output_dir)

    try:
        click.echo("\n")

        command = [aria2c_path,
                   "-i", str(aria2_file),
                   "-x", "4",
                   "-s", "4",
                   "--continue=true",
                   "--auto-file-renaming=false",
                   "--summary-interval=30",
                   "--console-log-level=warn"] + ctx.args

        utils.confirm(f"\nRunning command:\n  {' '.join(command)}\nContinue?", default=True, abort=True)
        click.echo("\n")
        subprocess.run(command, check=True)

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"aria2c failed with exit code {e.returncode}") from e

    finally:
        aria2_file.unlink(missing_ok=True)
