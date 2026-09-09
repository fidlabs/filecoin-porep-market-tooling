import os
import shutil
import subprocess
import tempfile

import click

from cli import utils
from cli._cli import is_dry_run
from cli.commands.migration_utils import migration_pairs, migration_service, print_status
from cli.commands.sp._sp import sp_organization_address
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.migration import MigrationError
from cli.services.web3_service import ActorId, Web3Service


def _organization_providers() -> set[ActorId]:
    return {
        provider.provider_id
        for provider in SPRegistry().get_provider_views_by_organization(sp_organization_address())
    }


@click.command("migration-status")
@click.argument("deal_id", type=click.IntRange(min=1), required=False)
def migration_status(deal_id: int | None):
    """Show chain-derived migration state and the next action."""
    service = migration_service()
    pairs = []
    errors = []
    try:
        for provider in _organization_providers():
            pairs.extend(service.discover(provider=provider, deal_id=deal_id))
            errors.extend(service.discovery_errors)
    except MigrationError as exc:
        raise click.ClickException(str(exc)) from exc
    for error in errors:
        click.echo(error, err=True)
    if deal_id is not None and not pairs:
        raise click.ClickException(f"V2 deal {deal_id} is not a verified migration deal for this SP organization")
    print_status(service, pairs)


def _sector_expirations(provider: ActorId, sectors: set[int]) -> dict[int, int]:
    result = {}
    for sector in sectors:
        info = Web3Service().state_sector_get_info(provider, sector)
        result[sector] = int((info or {}).get("Expiration", (info or {}).get("expiration", 0)))
    return result


@click.command("extend-deal-sectors")
@click.argument("deal_id", type=click.IntRange(min=1))
@click.option("--sptool", "sptool_path", envvar="SPTOOL_PATH", default="sptool", show_default=True)
def extend_deal_sectors(deal_id: int, sptool_path: str):
    """Extend every sector carrying a verified V1 claim for one V2 deal."""
    service, pairs = migration_pairs(deal_id=deal_id)
    pair = pairs[0]
    if pair.target.deal.provider_id not in _organization_providers():
        raise click.ClickException(f"V2 deal {deal_id} does not belong to this SP organization")
    try:
        plan = service.adoption_plan(pair)
    except MigrationError as exc:
        raise click.ClickException(str(exc)) from exc
    source_ids = {claim.claim_id for claim in plan.source_claims}
    if plan.extensions or plan.target_ids != source_ids:
        raise click.ClickException("Client preparation is incomplete; all V1 claims must be pending or confirmed first")
    if any(claim.end_epoch <= plan.sector_target_epoch for claim in plan.source_claims):
        raise click.ClickException("A claim does not extend beyond the required sector expiration")
    sectors = {claim.sector for claim in plan.source_claims}
    expirations = _sector_expirations(pair.source.provider, sectors)
    pending = {sector for sector, expiration in expirations.items() if expiration < plan.sector_target_epoch}
    if not pending:
        click.echo(f"V2 {deal_id}: all {len(sectors)} sector(s) already reach epoch {plan.sector_target_epoch}")
        return
    if Web3Service().mpool_pending_method(pair.source.provider, 32):
        raise click.ClickException(
            "This provider has a pending ExtendSectorExpiration2 message; wait before replaying the extension"
        )
    executable = shutil.which(sptool_path) if os.path.sep not in sptool_path else sptool_path
    if not executable or not os.path.isfile(executable):
        raise click.ClickException(f"sptool executable not found: {sptool_path}")
    with tempfile.NamedTemporaryFile("w", prefix="porep-migration-sectors-", delete=True) as sector_file:
        sector_file.write("".join(f"{sector}\n" for sector in sorted(pending)))
        sector_file.flush()
        base_command = [
            executable,
            "--actor",
            str(pair.source.provider),
            "sectors",
            "extend",
            "--sector-file",
            sector_file.name,
            "--new-expiration",
            str(plan.sector_target_epoch),
            "--tolerance",
            "0",
            "--max-sectors",
            str(min(len(pending), 500)),
        ]
        preview = subprocess.run(base_command, check=False, text=True, capture_output=True)
        if preview.returncode != 0:
            raise click.ClickException(f"sptool preview failed: {(preview.stderr or preview.stdout).strip()}")
        if "nothing to extend" in preview.stdout.lower():
            raise click.ClickException(
                "sptool cannot build the requested extension, usually because it would clamp or drop a claim"
            )
        click.echo(preview.stdout.strip())
        if is_dry_run():
            click.echo("Dry run: sptool preview completed; no sector message was sent")
            return
        utils.confirm(
            f"Extend {len(pending)} sector(s) for V2 {deal_id} to epoch {plan.sector_target_epoch}?",
            abort=True,
        )
        execute = subprocess.run(base_command + ["--really-do-it"], check=False, text=True, capture_output=True)
        if execute.returncode != 0:
            raise click.ClickException(f"sptool execution failed: {(execute.stderr or execute.stdout).strip()}")
        click.echo(execute.stdout.strip())
    readback = _sector_expirations(pair.source.provider, pending)
    incomplete = {sector for sector, expiration in readback.items() if expiration < plan.sector_target_epoch}
    if not incomplete:
        click.echo(f"V2 {deal_id}: sector extension confirmed on chain")
        return
    if Web3Service().mpool_pending_method(pair.source.provider, 32):
        raise click.ClickException(
            f"V2 {deal_id}: extension message is pending; {len(incomplete)} sector(s) are not confirmed yet"
        )
    raise click.ClickException(
        f"sptool exited successfully but {len(incomplete)} sector(s) remain below the target and no pending message was found"
    )
