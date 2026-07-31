"""End-to-end PoRep Market deal lifecycle test.

Runs the full flow against a live devnet through the real CLI:
propose → accept → init → allocate → onboard → verify-commp.

Steps are sequential and share state, so the whole lifecycle is a single
test function — a failed step aborts the rest instead of producing noise.
"""
from __future__ import annotations

import os
import pytest

from _utils._package import compute_commp, find_sptool, get_min_price_per_sector_per_month

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(900)]

DURATION_MONTHS = 6
RETRIEVABILITY_BPS = 10
BANDWIDTH_MBPS = 1
LATENCY_MS = 999
INDEXING_PCT = 0


def test_deal_lifecycle(porep_cli, generated_package, tmp_path):
    package = generated_package
    download_dir = tmp_path / "downloads"
    price = get_min_price_per_sector_per_month(manifest=package.manifest)

    print(f"\n========== [1/6] Proposing deal  manifest={package.manifest_url} ==========")
    before_deals = porep_cli.invoke_json(["client", "get-deals"])
    deal_id = max((int(deal["deal_id"]) for deal in before_deals), default=0) + 1
    porep_cli.invoke(
        [
            "client", "propose-deal-from-manifest", package.manifest_url,
            "--retrievability-bps", str(RETRIEVABILITY_BPS),
            "--bandwidth-mbps", str(BANDWIDTH_MBPS),
            "--price-per-sector-per-month", str(price),
            "--duration-months", str(DURATION_MONTHS),
            "--latency-ms", str(LATENCY_MS),
            "--indexing-pct", str(INDEXING_PCT),
        ],
        confirm_answers=["no", "yes", "yes", "yes"],
    )
    proposed_deals = porep_cli.wait_until(
        ["client", "get-deals", "proposed"],
        lambda deals: any(int(deal["deal_id"]) == deal_id for deal in deals),
        description=f"proposed deal  id={deal_id}",
    )

    proposed_deal = next(deal for deal in proposed_deals if int(deal["deal_id"]) == deal_id)
    assert proposed_deal.get("manifest_location") == package.manifest_url, (
        f"deal {deal_id} belongs to someone else: "
        f"manifest_location={proposed_deal.get('manifest_location')} != {package.manifest_url}"
    )
    print(f"deal_id={deal_id}")

    print(f"\n========== [2/6] Accepting deal  id={deal_id} ==========")
    porep_cli.invoke(["sp", "accept-deal", str(deal_id)], auto_confirm=True)
    porep_cli.wait_until(
        ["client", "get-deal", str(deal_id)],
        lambda deal: str(deal.get("state", "")).upper() == "ACCEPTED",
        description=f"deal {deal_id} state=ACCEPTED",
    )

    print(f"\n========== [3/6] Initializing deal  id={deal_id} ==========")
    porep_cli.invoke(["client", "init-accepted-deals", str(deal_id)], auto_confirm=True)
    porep_cli.wait_until(
        ["client", "get-deal", str(deal_id)],
        lambda deal: int(deal.get("rail_id", 0)) > 0 and bool(deal.get("validator_address")),
        description=f"deal {deal_id} initialized (rail_id, validator_address)",
    )

    print(f"\n========== [4/6] Making allocations  id={deal_id} ==========")
    porep_cli.invoke(["client", "make-allocations", str(deal_id)], auto_confirm=True)
    porep_cli.wait_until(
        ["client", "get-deal", str(deal_id)],
        lambda deal: str(deal.get("state", "")).upper() == "COMPLETED",
        description=f"deal {deal_id} state=COMPLETED",
    )

    print(f"\n========== [5/6] Downloading pieces  id={deal_id} ==========")
    is_https = package.manifest_url.startswith("https://")
    porep_cli.invoke(
        [
            "sp", "onboard-data", str(deal_id),
            "--output-dir", str(download_dir),
            "--host", package.manifest_url,
            "--port", "443" if is_https else str(package.port),
        ],
        auto_confirm=True,
    )

    print(f"\n========== [6/6] Verifying downloaded pieces  id={deal_id} ==========")
    downloaded = sorted(p.name for p in download_dir.glob("*.car"))
    expected = sorted(piece["storagePath"] for piece in package.manifest[0]["pieces"])
    assert downloaded == expected, f"downloaded pieces {downloaded} != manifest pieces {expected}"

    # TODO replace with commP verification after it will be implemented
    sptool = find_sptool(os.getenv("SPTOOL_PATH") or None)
    for piece in package.manifest[0]["pieces"]:
        commp_cid, _, _ = compute_commp(sptool, download_dir / piece["storagePath"])
        assert commp_cid == piece["pieceCid"], (
            f"commP mismatch for {piece['storagePath']}: {commp_cid} != {piece['pieceCid']}"
        )
