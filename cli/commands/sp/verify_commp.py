import json
import subprocess
from pathlib import Path

import click

from cli import utils


@click.command()
@click.option("--pieces-dir", type=click.Path(exists=True, file_okay=False), required=True,
              help="Directory containing the downloaded pieces and their manifest.")
def verify_commp(pieces_dir: str) -> None:
    """
    Verify the commP of downloaded pieces against their manifest.

    Expects manifest.json (or the manifest_<dealId>.json written by onboard-data)
    to be in the pieces directory.
    """

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

    verify_pieces(manifest, _pieces_dir)

def verify_pieces(manifest: list[dict], pieces_dir: Path) -> None:
    sptool_path = _get_sptool_path()

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


def _parse_commp_output(output: str) -> dict:
    fields = {}

    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip().replace(" ", "_").lower()] = value.strip()

    return fields


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
