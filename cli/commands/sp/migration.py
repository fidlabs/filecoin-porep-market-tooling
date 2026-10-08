import os
import shutil
import subprocess
import tempfile

import click

from cli import utils
from cli._cli import is_dry_run
from cli.commands.migration_utils import epochs_to_days
from cli.commands.sp._sp import sp_organization_address
from cli.services.contracts.datacap_evidence_adapter import DataCapEvidenceAdapter
from cli.services.contracts.porep_market_view_helper import PoRepMarketDealView, PoRepMarketViewHelper
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.migration import Claim, MigrationError, adapter_claim_ids, sector_target_epoch
from cli.services.web3_service import ActorId, Web3Service


def deal_claims(target: PoRepMarketDealView) -> list[Claim]:
    adapter = DataCapEvidenceAdapter(target.deal.evidence_adapter_address)
    ids = adapter_claim_ids(adapter, target.deal.deal_id)
    if not ids:
        raise MigrationError(f"V2 deal {target.deal.deal_id} has no claims on its adapter yet; the client has to run adopt-v1-claims first")
    rpc_claims = Web3Service().state_get_claims(target.deal.provider_id)
    claims = []
    for claim_id in ids:
        raw = rpc_claims.get(str(claim_id))
        if raw is None:
            raise MigrationError(f"Claim {claim_id} is not held by provider {target.deal.provider_id}")
        claims.append(Claim.from_rpc(claim_id, raw))
    return claims


def sector_expirations(provider: ActorId, sectors: set[int]) -> dict[int, int]:
    result = {}
    for sector in sorted(sectors):
        info = Web3Service().state_sector_get_info(provider, sector)
        if info is None:
            raise MigrationError(f"Sector {sector} of provider {provider} is not live on chain")
        result[sector] = int(info.get("Expiration", 0))
    return result


def _sptool_executable(sptool_path: str) -> str:
    executable = shutil.which(sptool_path) if os.path.sep not in sptool_path else sptool_path
    if not executable or not os.path.isfile(executable):
        raise click.ClickException(f"sptool executable not found: {sptool_path}; install lotus sptool or pass --sptool / SPTOOL_PATH")
    return executable


def _run_sptool(command: list[str], sector_count: int) -> str:
    result = subprocess.run(command, check=False, text=True, capture_output=True)
    output = (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")
    if result.returncode != 0:
        raise click.ClickException(f"sptool failed ({result.returncode}):\n{output.strip()}")
    skipped = [line for line in output.splitlines() if "skipping sector" in line.lower()]
    if skipped:
        click.echo(f"sptool skipped {len(skipped)} sector(s):")
        for line in skipped:
            click.echo(f"  {line.strip()}")
    if skipped and len(skipped) >= sector_count:
        raise click.ClickException("sptool would skip every sector, usually because another claim in the sector ends before the target; "
                                   "pick a lower --target-epoch or ask the admin")
    return output.strip()


@click.command("extend-deal-sectors")
@click.argument("v2_deal_id", type=click.IntRange(min=1))
@click.option("--print-only", is_flag=True, help="Only write the sector file and print the sptool command.")
@click.option("--sptool", "sptool_path", envvar="SPTOOL_PATH", default="sptool", show_default=True, show_envvar=True,
              help="Path to the lotus sptool binary.")
@click.option("--target-epoch", type=click.IntRange(min=1), help="Required sector expiration; default derived from the V2 deal.")
@click.option("--sector-file", type=click.Path(dir_okay=False, writable=True), help="Where to write the sector list.  [default: temp file]")
def extend_deal_sectors(v2_deal_id: int, print_only: bool, sptool_path: str, target_epoch: int | None, sector_file: str | None):
    """
    Extend the sectors holding the claims of a migrated V2 deal.

    Reads the claim IDs from the V2 evidence adapter, maps them to sectors on chain, writes the sectors that
    expire before the target epoch to a file and runs `sptool sectors extend` on them. No resealing, no claim drop.
    Re-run after the message lands to verify.

    V2_DEAL_ID - The V2 deal whose sectors to extend.
    """

    target = PoRepMarketViewHelper().get_deal_view(v2_deal_id)
    provider = target.deal.provider_id
    organization_providers = {view.provider_id for view in SPRegistry().get_provider_views_by_organization(sp_organization_address())}
    if provider not in organization_providers:
        raise click.ClickException(f"V2 deal {v2_deal_id} provider {provider} does not belong to organization {sp_organization_address()}")

    current_epoch = Web3Service().get_block_number()
    target_epoch = target_epoch or sector_target_epoch(target, current_epoch)
    try:
        claims = deal_claims(target)
        expirations = sector_expirations(provider, {claim.sector for claim in claims})
    except MigrationError as exc:
        raise click.ClickException(str(exc)) from exc

    earliest_claim_end = min(claim.end_epoch for claim in claims)
    click.echo(f"V2 deal {v2_deal_id}: {target.deal.state}, provider {provider}, {len(claims)} claim(s) in {len(expirations)} sector(s)")
    click.echo(f"Target sector expiration: epoch {target_epoch} ({epochs_to_days(target_epoch - current_epoch)} from now); "
               f"earliest claim end: epoch {earliest_claim_end}")
    if earliest_claim_end < target_epoch:
        click.echo("Warning: some claims end before the target epoch; sptool may clamp or skip those sectors")

    below = {sector: expiration for sector, expiration in expirations.items() if expiration < target_epoch}
    for sector, expiration in expirations.items():
        marker = "extend" if sector in below else "ok"
        click.echo(f"  sector {sector}: expires at epoch {expiration} ({epochs_to_days(expiration - current_epoch)} from now) {marker}")
    if not below:
        click.echo(f"\nAll sectors already reach epoch {target_epoch}; nothing to extend.")
        return

    if sector_file is None:
        handle, sector_file = tempfile.mkstemp(prefix=f"porep-v2-deal-{v2_deal_id}-sectors-", suffix=".txt")
        os.close(handle)
    with open(sector_file, "w", encoding="utf-8") as file:
        file.write("".join(f"{sector}\n" for sector in sorted(below)))
    click.echo(f"\n{len(below)} sector(s) to extend written to {sector_file}")

    command = [sptool_path, "--actor", str(provider), "sectors", "extend",
               "--sector-file", sector_file, "--new-expiration", str(target_epoch), "--tolerance", "0"]
    click.echo("sptool command: " + " ".join(command) + " --really-do-it")
    if print_only or is_dry_run():
        return

    command[0] = _sptool_executable(sptool_path)
    click.echo("\nsptool preview:")
    click.echo(_run_sptool(command, len(below)))
    utils.confirm(f"\nExtend {len(below)} sector(s) of {provider} to epoch {target_epoch}?", abort=True)
    click.echo(_run_sptool(command + ["--really-do-it"], len(below)))
    click.echo(f"\nExtension message sent. Re-run `extend-deal-sectors {v2_deal_id}` after it lands to verify the new expirations.")
