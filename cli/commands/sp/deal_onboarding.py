import json
import logging
import subprocess
import tempfile
from pathlib import Path

import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.sp import _utils as sp_utils
from cli.services.contracts.client_contract import ClientContract
from cli.services.contracts.porep_market import PoRepMarket, PoRepMarketDealProposal, PoRepMarketDealState
from cli.services.web3_service import FilAddress, Web3Service

logger = logging.getLogger(__name__)


def verify_executable(default: str, env_name: str, install_hint: str) -> str:
    executable = utils.get_env_required(env_name, default=default)

    if executable != default:
        executable = str(Path(executable).resolve())

    try:
        subprocess.run([executable, "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception as e:
        raise click.ClickException(f"{executable} not found ({env_name}). {install_hint}\n{e}") from e

    return executable


def get_aria2c_path() -> str:
    return verify_executable("aria2c", "ARIA2C_PATH", "See https://aria2.github.io/")


def get_curio_path() -> str:
    return verify_executable("curio", "CURIO_PATH", "See https://docs.curiostorage.org/installation")


def get_boostd_path() -> str:
    return verify_executable("boostd", "BOOSTD_PATH", "See https://boost.filecoin.io/getting-started")


def write_aria2c_input_file(manifest: list[dict], download_host: str, output_dir: Path) -> Path:
    output_dir = output_dir.resolve()

    with tempfile.NamedTemporaryFile(delete=False) as f:
        aria2_file = Path(f.name)

    pieces = manifest[0]["pieces"]

    with open(aria2_file, "w", encoding="utf-8") as f:
        for piece in pieces:
            storage_path = piece["storagePath"]
            output_file = (output_dir / storage_path).resolve()
            piece_name = storage_path.removesuffix(".car")

            try:
                output_file.relative_to(output_dir)
            except ValueError as e:
                raise click.ClickException(f"Invalid manifest piece storagePath: {storage_path}") from e

            download_url = f"{download_host}/piece/{piece_name}"

            f.write(f"{download_url}\n")
            f.write(f"  out={output_file.name}\n")
            f.write(f"  dir={output_file.parent}\n")

    return aria2_file.resolve()


def write_manifest_file(manifest: list[dict], output_dir: Path, deal_id: int, *, overwrite: bool = False) -> Path:
    manifest_file = output_dir / f"manifest_{deal_id}.json"

    if manifest_file.exists() and not overwrite:
        with open(manifest_file, "r", encoding="utf-8") as f:
            existing_manifest = json.load(f)

        if utils.json_pretty(existing_manifest, True) != utils.json_pretty(manifest, True):
            utils.confirm(
                f"A different manifest already exists in the output directory: {manifest_file}\n"
                "Do you want to overwrite it?",
                abort=True,
            )

    with open(manifest_file, "w", encoding="utf-8") as f:
        f.write(utils.json_pretty(manifest))

    return manifest_file.resolve()


def download_deal_data(
    deal_id: int,
    output_dir: Path,
    *,
    host: str | None = None,
    port: int = 7777,
    aria2c_extra_args: list[str] | None = None,
    interactive: bool = True,
) -> tuple[PoRepMarketDealProposal, list[dict]]:
    deal = PoRepMarket().get_deal_proposal(deal_id)

    if deal.state != PoRepMarketDealState.COMPLETED:
        raise click.ClickException(f"Deal id {deal_id} is not in COMPLETED state (current: {deal.state})")

    manifest = commands_utils.fetch_manifest(deal.manifest_location, show_manifest=False, retries=10, quiet=not interactive)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_manifest_file(manifest, output_dir, deal_id, overwrite=not interactive)

    if host and not host.startswith(("http://", "https://")):
        host = f"http://{host}"

    parsed_url = commands_utils.validate_and_parse_url(host or deal.manifest_location)
    download_host = f"{parsed_url.scheme or 'http'}://{parsed_url.hostname}:{port}"
    aria2_file = write_aria2c_input_file(manifest, download_host, output_dir)

    aria2c_path = get_aria2c_path()
    command = [
        aria2c_path,
        "-i", str(aria2_file),
        "-x", "4",
        "-s", "4",
        "--continue=true",
        "--auto-file-renaming=false",
        "--summary-interval=30",
        "--console-log-level=warn",
    ] + (aria2c_extra_args or [])

    if interactive:
        click.echo(f"\nDownloading {len(manifest[0]['pieces'])} .car files for deal {deal_id}")
        utils.confirm(f"\nRunning command:\n  {' '.join(command)}\nContinue?", default=True, abort=True)
        click.echo()

    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"aria2c failed with exit code {e.returncode}") from e
    finally:
        aria2_file.unlink(missing_ok=True)

    return deal, manifest


def data_piece_paths(manifest: list[dict], output_dir: Path) -> list[Path]:
    return [
        (output_dir / piece["storagePath"]).resolve()
        for piece in manifest[0]["pieces"]
        if piece["pieceType"] == "data"
    ]


def prepare_boost_cars_dir(manifest: list[dict], download_dir: Path, cars_dir: Path) -> None:
    cars_dir.mkdir(parents=True, exist_ok=True)

    for piece in manifest[0]["pieces"]:
        if piece["pieceType"] != "data":
            continue

        cid = piece["pieceCid"]
        source = (download_dir / piece["storagePath"]).resolve()
        target = (cars_dir / f"{cid}.car").resolve()

        if not source.exists():
            raise click.ClickException(f"Missing downloaded piece for boost: {source}")

        if target.exists() or target.is_symlink():
            target.unlink()

        target.symlink_to(source)


def build_curio_command(
    curio_path: str,
    client_contract_filecoin_address: FilAddress,
    allocation_id: int,
    deal: PoRepMarketDealProposal,
) -> list[str]:
    return [
        curio_path,
        "market",
        "ddo",
        "--actor",
        str(deal.provider_id),
        client_contract_filecoin_address,
        str(allocation_id),
    ]


def build_boost_command(boostd_path: str, allocation_id: int, cid: str, cars_dir: Path) -> list[str]:
    return [
        boostd_path,
        "import-direct",
        "--allocation-id",
        str(allocation_id),
        cid,
        str(cars_dir / f"{cid}.car"),
    ]


def claim_deal_allocations(
    software: str,
    deal_id: int,
    *,
    cars_dir: Path | None = None,
    extra_args: list[str] | None = None,
    interactive: bool = True,
) -> list[dict]:
    software = software.lower()
    deal = PoRepMarket().get_deal_proposal(deal_id)
    deal_allocations = sp_utils.get_deal_allocations(deal)

    if not deal_allocations:
        raise click.ClickException(f"No allocations found for deal id {deal_id}")

    if interactive:
        click.echo(
            f"Found {len(deal_allocations)} allocations for deal id {deal_id}: "
            f"{utils.json_pretty(deal_allocations)}\n"
        )

    if software == "curio":
        curio_path = get_curio_path()
        client_contract_filecoin_address = ClientContract().address().to_filecoin_address()

        def build_command(allocation_id: int, cid: str, **_kwargs) -> list[str]:
            return build_curio_command(curio_path, client_contract_filecoin_address, allocation_id, deal)

    elif software == "boost":
        if not cars_dir:
            raise click.UsageError("cars_dir is required when software is boost")

        boostd_path = get_boostd_path()
        resolved_cars_dir = cars_dir.resolve()

        def build_command(allocation_id: int, cid: str, **_kwargs) -> list[str]:
            return build_boost_command(boostd_path, allocation_id, cid, resolved_cars_dir)
    else:
        raise click.ClickException(f"Unsupported software: {software}")

    claimed: list[dict] = []

    for allocation in deal_allocations:
        command = build_command(
            allocation_id=allocation["allocationId"],
            cid=allocation["CID"],
        ) + (extra_args or [])

        if interactive:
            if not utils.confirm(
                f"\nRunning command:\n  {' '.join(command)}\nContinue?",
                session_id="claim-allocation",
                default=True,
            ):
                click.echo("Skipped this allocation")
                continue
            click.echo()

        try:
            subprocess.run(command, check=True)
            claimed.append(allocation)
        except subprocess.CalledProcessError as e:
            if interactive:
                click.echo(f"\nCommand failed with exit code {e.returncode}")
            raise RuntimeError(
                f"Failed to claim allocation {allocation['allocationId']} for deal {deal_id}: exit {e.returncode}"
            ) from e

    if len(claimed) != len(deal_allocations):
        raise RuntimeError(
            f"Claimed {len(claimed)} of {len(deal_allocations)} allocations for deal {deal_id}"
        )

    return claimed


def cleanup_deal_files(output_dir: Path, deal_id: int, manifest: list[dict]) -> None:
    manifest_file = output_dir / f"manifest_{deal_id}.json"
    manifest_file.unlink(missing_ok=True)

    for path in data_piece_paths(manifest, output_dir):
        path.unlink(missing_ok=True)

        parent = path.parent
        if parent != output_dir and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()


def block_at_or_after_timestamp(timestamp: int) -> int:
    w3 = Web3Service().w3()
    latest = w3.eth.block_number
    low, high = 0, latest

    while low < high:
        mid = (low + high) // 2
        block_ts = w3.eth.get_block(mid)["timestamp"]

        if block_ts < timestamp:
            low = mid + 1
        else:
            high = mid

    return low


def deal_meets_min_block(deal: PoRepMarketDealProposal, min_block: int | None) -> bool:
    if min_block is None:
        return True

    return deal.proposed_at_block >= min_block
