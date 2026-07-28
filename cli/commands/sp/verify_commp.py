import functools
import subprocess
from pathlib import Path

import click

from cli import utils
from cli.commands.config import commands_utils
from cli.services.contracts.porep_market import PoRepMarket


@click.command()
@click.argument("car_file_paths", nargs=-1, type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path))
def verify_commp(car_file_paths: tuple[Path]):
    """
    Compute and print the commP of one or more .car files.

    Unlike verify-commp-manifest/verify-commp-deal, this does not compare
    against a manifest; it just prints the commP, piece size and car file size.

    CAR_FILE_PATHS - One or more paths to .car files, separated by spaces.
    A shell glob is expanded by the shell into multiple paths, e.g. /tmp/test-pieces/*.

    \b
    Examples:
      verify-commp /tmp/test-pieces/baga6ea4seaq....car
      verify-commp /tmp/test-pieces/*
    """

    click.echo("Verifying commP of given files...")

    commps = []
    for car_file_path in car_file_paths:
        try:
            result = run_commp_command(car_file_path)
        except subprocess.CalledProcessError as e:
            raise click.ClickException(f"Failed to compute commP for {car_file_path}:\n{e.stderr}") from e

        result["car_file_path"] = car_file_path.as_posix()
        commps.append(result)

    click.echo(utils.json_pretty(commps))


@click.command()
@click.argument("manifest_file_path", type=click.Path(exists=True, dir_okay=False, file_okay=True, path_type=Path))
@click.argument("car_files_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
def verify_commp_manifest(manifest_file_path: Path, car_files_dir: Path):
    """
    Verify the commP of .car files against a manifest file.

    Each piece in the manifest is matched to a .car file in CAR_FILES_DIR by its
    storagePath, and its commP, piece size and car file size are checked.

    MANIFEST_FILE_PATH - Path to the manifest JSON file (e.g. the manifest_<dealId>.json written by onboard-data).
    CAR_FILES_DIR - Directory containing the .car files referenced by the manifest.
    """

    manifest = commands_utils.fetch_local_manifest(manifest_file_path.resolve())

    verify_pieces(manifest, car_files_dir)


@click.command()
@click.argument("deal_id", type=click.IntRange(min=1))
@click.argument("car_files_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
def verify_commp_deal(deal_id: int, car_files_dir: Path):
    """
    Verify the commP of .car files against a deal's manifest.

    Fetches the deal's manifest, then matches each piece to a .car file in
    CAR_FILES_DIR by its storagePath and checks its commP, piece size and car file size.

    DEAL_ID - ID of the deal whose manifest to verify against.
    CAR_FILES_DIR - Directory containing the .car files for the deal.
    """

    deal = PoRepMarket().get_deal_proposal(deal_id)
    manifest = commands_utils.fetch_manifest(deal.manifest_location, show_manifest=False, quiet=True, retries=10)
    verify_pieces(manifest, car_files_dir)


def run_commp_command(car_path: str):
    result = subprocess.run(
        [_get_sptool_path(), "--actor", "any", "toolbox", "mk12-client", "commp", str(car_path)],
        check=True, capture_output=True, text=True)

    return _parse_commp_output(result.stdout)


def verify_pieces(manifest: list[dict], car_files_dir: Path):
    pieces = manifest[0]["pieces"]
    failed = 0
    expected_car_files = {Path(piece["storagePath"]).as_posix() for piece in pieces}
    if len(expected_car_files) != len(manifest[0]["pieces"]):
        raise click.ClickException(f"Expected {len(expected_car_files)} car files, but found {len(manifest[0]['pieces'])} in manifest")

    for piece in pieces:
        storage_path = piece["storagePath"]
        car_path = (car_files_dir / storage_path).resolve()

        if car_files_dir not in car_path.parents:
            click.secho(f"x {car_path}", fg="yellow")
            _format_commp_warnings([f"File not found: {car_path}"])
            failed += 1
            continue

        if not car_path.is_file():
            click.secho(f"x {car_path}", fg="yellow")
            _format_commp_warnings(["File not found"])
            failed += 1
            continue

        try:
            result = run_commp_command(car_path)
        except subprocess.CalledProcessError as e:
            raise click.ClickException(f"Failed to compute commP for {car_path}:\n{e.stderr}") from e

        warnings = _get_commp_warnings(result, piece)

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


@functools.lru_cache(maxsize=1)
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


def _get_commp_warnings(result: dict, piece: dict) -> list[str]:
    warnings = []
    required_fields = ["commp_cid", "piece_size", "car_file_size"]
    missing = [k for k in required_fields if result.get(k) is None]
    if missing:
        warnings.append(f"Unexpected sptool output (missing {', '.join(missing)})")
        return warnings

    try:
        if result["commp_cid"] != piece.get("pieceCid"):
            warnings.append(f"CommP CID mismatch: {result['commp_cid']} != {piece.get('pieceCid')}")

        if int(result["piece_size"]) != piece.get("pieceSize"):
            warnings.append(f"Piece size mismatch: {result['piece_size']} != {piece.get('pieceSize')}")

        expected_file_size = piece.get("fileSize")
        if expected_file_size is not None and int(result["car_file_size"]) != expected_file_size:
            warnings.append(f"Car file size mismatch: {result['car_file_size']} != {expected_file_size}")

    except ValueError as e:
        warnings.append(f"Unexpected sptool output value: {e}")

    return warnings


def _format_commp_warnings(warnings: list[str]):
    for i, warning in enumerate(warnings):
        prefix = "└──" if i == len(warnings) - 1 else "├──"
        click.secho(f"  {prefix} {warning}", fg="yellow")
