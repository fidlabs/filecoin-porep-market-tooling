#!/usr/bin/env python3
"""
Periodically onboard COMPLETED PoRep Market deals for a storage provider.

Tracks successfully onboarded deals in a local JSON state file because the
on-chain contract has no ONBOARDED deal state.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_environment() -> None:
    if (REPO_ROOT / ".env").exists():
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=REPO_ROOT / ".env")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automatically download and onboard COMPLETED PoRep Market deals for an SP.",
    )
    parser.add_argument(
        "--organization",
        default=os.getenv("SP_ORGANIZATION"),
        help="SP organization EVM address (default: SP_ORGANIZATION env var).",
    )
    parser.add_argument(
        "--software",
        required=True,
        choices=["curio", "boost"],
        help="Onboarding software to use when claiming allocations.",
    )
    parser.add_argument(
        "--download-dir",
        required=True,
        type=Path,
        help="Directory where deal .car files are downloaded before onboarding.",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        help="JSON file tracking onboarded deal IDs (default: <download-dir>/.onboarded_deals.json).",
    )
    parser.add_argument(
        "--min-date",
        help="Ignore deals proposed before this UTC date (ISO-8601, e.g. 2025-06-01 or 2025-06-01T00:00:00Z).",
    )
    parser.add_argument(
        "--min-block",
        type=int,
        help="Ignore deals with proposed_at_block below this value (overrides --min-date when both are set).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=3600,
        help="Seconds between checks when running continuously (default: 3600).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single check cycle and exit (useful with cron/systemd timers).",
    )
    parser.add_argument(
        "--manifest-host",
        help="Host for .car downloads (default: host from each deal's manifest URL).",
    )
    parser.add_argument(
        "--manifest-port",
        type=int,
        default=7777,
        help="Port for .car downloads (default: 7777).",
    )
    parser.add_argument(
        "--provider-id",
        type=int,
        help="Only process deals for this Filecoin provider actor id.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args()


def _resolve_min_block(args: argparse.Namespace) -> int | None:
    from cli.commands.sp import deal_onboarding

    if args.min_block is not None:
        return args.min_block

    if not args.min_date:
        return None

    parsed = datetime.fromisoformat(args.min_date.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return deal_onboarding.block_at_or_after_timestamp(int(parsed.timestamp()))


def _resolve_organization(organization: str | None):
    from cli.services.web3_service import EthAddress, FilAddress

    if not organization:
        raise SystemExit("SP organization is required: set SP_ORGANIZATION or pass --organization")

    if FilAddress.is_filecoin_address(organization):
        return EthAddress.from_filecoin_address(organization)

    return EthAddress(organization)


def _cleanup_deal_dir(deal_dir: Path, deal_id: int, manifest: list[dict] | None) -> None:
    from cli.commands.sp import deal_onboarding

    boost_cars_dir = deal_dir / "boost_cars"

    try:
        if manifest is not None:
            deal_onboarding.cleanup_deal_files(deal_dir, deal_id, manifest)
        else:
            manifest_path = deal_dir / f"manifest_{deal_id}.json"
            if manifest_path.exists():
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                deal_onboarding.cleanup_deal_files(deal_dir, deal_id, manifest)

        if boost_cars_dir.exists():
            for path in boost_cars_dir.iterdir():
                path.unlink(missing_ok=True)
            boost_cars_dir.rmdir()

        if deal_dir.exists() and not any(deal_dir.iterdir()):
            deal_dir.rmdir()
    except Exception:
        logging.exception("Failed to clean up files for deal %s in %s", deal_id, deal_dir)


def _process_deal(
    deal,
    *,
    software: str,
    download_dir: Path,
    state,
    min_block: int | None,
    manifest_host: str | None,
    manifest_port: int,
) -> bool:
    from cli.commands.sp import deal_onboarding

    deal_id = deal.deal_id

    if state.is_onboarded(deal_id):
        logging.info("Deal %s already onboarded (local state); skipping", deal_id)
        return False

    deal_dir = download_dir / f"deal_{deal_id}"
    boost_cars_dir = deal_dir / "boost_cars"
    manifest: list[dict] | None = None

    logging.info("Onboarding deal %s (provider %s)", deal_id, deal.provider_id)

    try:
        _, manifest = deal_onboarding.download_deal_data(
            deal_id,
            deal_dir,
            host=manifest_host,
            port=manifest_port,
            interactive=False,
        )

        cars_dir = None
        if software == "boost":
            deal_onboarding.prepare_boost_cars_dir(manifest, deal_dir, boost_cars_dir)
            cars_dir = boost_cars_dir

        deal_onboarding.claim_deal_allocations(
            software,
            deal_id,
            cars_dir=cars_dir,
            interactive=False,
        )

        state.mark_onboarded(deal_id, software=software, provider_id=int(deal.provider_id))
        logging.info("Deal %s onboarded successfully", deal_id)
        return True

    except Exception:
        logging.exception("Failed to onboard deal %s", deal_id)
        return False

    finally:
        if deal_dir.exists():
            _cleanup_deal_dir(deal_dir, deal_id, manifest)


def run_cycle(args: argparse.Namespace) -> tuple[int, int]:
    from cli.commands import utils as commands_utils
    from cli.commands.sp import deal_onboarding
    from cli.commands.sp.onboard_state import OnboardState
    from cli.services.contracts.porep_market import PoRepMarketDealState

    organization = _resolve_organization(args.organization)
    min_block = _resolve_min_block(args)
    download_dir = args.download_dir.resolve()
    download_dir.mkdir(parents=True, exist_ok=True)

    state_path = (args.state_file or (download_dir / ".onboarded_deals.json")).resolve()
    state: OnboardState = OnboardState.load(state_path)

    deals = commands_utils.get_all_deals(PoRepMarketDealState.COMPLETED, organization)

    if args.provider_id is not None:
        deals = [deal for deal in deals if int(deal.provider_id) == args.provider_id]

    deals.sort(key=lambda deal: deal.deal_id)

    logging.info(
        "Found %s completed deal(s) for organization %s (min_block=%s, state_file=%s)",
        len(deals),
        organization,
        min_block,
        state_path,
    )

    processed = 0
    onboarded = 0

    for deal in deals:
        if state.is_onboarded(deal.deal_id):
            continue

        if not deal_onboarding.deal_meets_min_block(deal, min_block):
            logging.info(
                "Deal %s proposed at block %s is before min block %s; skipping",
                deal.deal_id,
                deal.proposed_at_block,
                min_block,
            )
            continue

        processed += 1
        if _process_deal(
            deal,
            software=args.software,
            download_dir=download_dir,
            state=state,
            min_block=min_block,
            manifest_host=args.manifest_host,
            manifest_port=args.manifest_port,
        ):
            onboarded += 1

    return processed, onboarded


def main() -> int:
    if sys.version_info < (3, 10):
        print(f"Python >= 3.10 required, found {sys.version}", file=sys.stderr)
        return 1

    _load_environment()
    args = _parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        while True:
            processed, onboarded = run_cycle(args)
            logging.info("Cycle finished: %s deal(s) processed, %s onboarded", processed, onboarded)

            if args.once:
                break

            logging.info("Sleeping %s seconds until next check", args.interval)
            time.sleep(args.interval)

    except KeyboardInterrupt:
        logging.info("Stopped by user")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
