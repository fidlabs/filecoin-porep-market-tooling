import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cli.commands.sp import deal_onboarding
from cli.commands.sp.onboard_state import OnboardState
from cli.services.contracts.porep_market import (
    PoRepMarketDealProposal,
    PoRepMarketDealState,
    PoRepMarketDealTerms,
)
from cli.services.contracts.sp_registry import SPRegistrySLIThresholds
from cli.services.web3_service import ActorId, EthAddress


def _load_auto_onboard_module():
    path = REPO_ROOT / "scripts" / "sp_auto_onboard.py"
    spec = importlib.util.spec_from_file_location("sp_auto_onboard", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def _sample_manifest(cid: str = "bafydata", storage_path: str = "data/piece.car") -> list[dict]:
    return [{
        "pieces": [
            {
                "pieceCid": "bafydag",
                "pieceType": "dag",
                "pieceSize": 1048576,
                "preparationId": "prep",
                "attachmentId": "attach",
                "storagePath": "dag.car",
            },
            {
                "pieceCid": cid,
                "pieceType": "data",
                "pieceSize": 1048576,
                "preparationId": "prep",
                "attachmentId": "attach",
                "storagePath": storage_path,
            },
        ],
    }]


def _sample_deal(deal_id: int = 1, proposed_at_block: int = 100) -> PoRepMarketDealProposal:
    return PoRepMarketDealProposal(
        deal_id=deal_id,
        client_address=EthAddress("0x4300EbD613b8E965A81B54aCdF1fA843758420DA"),
        provider_id=ActorId(12345),
        requirements=SPRegistrySLIThresholds(9900, 100, 200, 100),
        terms=PoRepMarketDealTerms(32 * 1024 ** 3, 1, 30),
        validator_address=EthAddress("0x4300EbD613b8E965A81B54aCdF1fA843758420DA"),
        state=PoRepMarketDealState.COMPLETED,
        rail_id=1,
        proposed_at_block=proposed_at_block,
        manifest_location="https://example.com/manifest.json",
    )


class OnboardStateTests(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = OnboardState.load(path)
            self.assertFalse(state.is_onboarded(7))

            state.mark_onboarded(7, software="curio", provider_id=12345)
            reloaded = OnboardState.load(path)

            self.assertTrue(reloaded.is_onboarded(7))
            self.assertEqual(reloaded.deals[7].software, "curio")
            self.assertEqual(reloaded.deals[7].provider_id, 12345)

            with open(path, encoding="utf-8") as f:
                raw = json.load(f)

            self.assertIn("7", raw["onboarded_deals"])


class DealOnboardingHelperTests(unittest.TestCase):
    def test_deal_meets_min_block(self):
        deal = _sample_deal(proposed_at_block=200)
        self.assertTrue(deal_onboarding.deal_meets_min_block(deal, None))
        self.assertTrue(deal_onboarding.deal_meets_min_block(deal, 200))
        self.assertFalse(deal_onboarding.deal_meets_min_block(deal, 201))

    def test_write_aria2c_input_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            manifest = _sample_manifest(storage_path="subdir/piece.car")
            aria2_file = deal_onboarding.write_aria2c_input_file(
                manifest,
                "http://manifest.example:7777",
                output_dir,
            )

            content = aria2_file.read_text(encoding="utf-8")
            self.assertIn("http://manifest.example:7777/piece/subdir/piece", content)
            self.assertIn("out=piece.car", content)
            aria2_file.unlink()

    def test_prepare_boost_cars_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            download_dir = Path(tmp)
            cars_dir = download_dir / "boost_cars"
            manifest = _sample_manifest(cid="bafytest", storage_path="data/piece.car")

            piece_path = download_dir / "data" / "piece.car"
            piece_path.parent.mkdir(parents=True)
            piece_path.write_bytes(b"car-data")

            deal_onboarding.prepare_boost_cars_dir(manifest, download_dir, cars_dir)

            link = cars_dir / "bafytest.car"
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), piece_path.resolve())

    def test_cleanup_deal_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            manifest = _sample_manifest(storage_path="data/piece.car")
            deal_id = 99

            piece_path = output_dir / "data" / "piece.car"
            piece_path.parent.mkdir(parents=True)
            piece_path.write_bytes(b"car-data")
            manifest_path = deal_onboarding.write_manifest_file(manifest, output_dir, deal_id, overwrite=True)

            deal_onboarding.cleanup_deal_files(output_dir, deal_id, manifest)

            self.assertFalse(piece_path.exists())
            self.assertFalse(manifest_path.exists())


class SpAutoOnboardScriptTests(unittest.TestCase):
    def test_resolve_min_block_from_min_block_arg(self):
        auto_onboard = _load_auto_onboard_module()
        namespace = mock.Mock(min_block=42, min_date=None)
        self.assertEqual(auto_onboard._resolve_min_block(namespace), 42)

    def test_run_cycle_skips_onboarded_deals(self):
        auto_onboard = _load_auto_onboard_module()

        with tempfile.TemporaryDirectory() as tmp:
            download_dir = Path(tmp)
            state_path = download_dir / ".onboarded_deals.json"
            state = OnboardState.load(state_path)
            state.mark_onboarded(1, software="curio", provider_id=12345)

            args = mock.Mock(
                organization="0xfF000000000000000000000000000000002847Cc",
                min_block=None,
                min_date=None,
                download_dir=download_dir,
                state_file=state_path,
                provider_id=None,
                software="curio",
                manifest_host=None,
                manifest_port=7777,
            )

            deal = _sample_deal(deal_id=1)

            with mock.patch.object(auto_onboard, "_resolve_organization", return_value=EthAddress(args.organization)), \
                    mock.patch("cli.commands.utils.get_all_deals", return_value=[deal]), \
                    mock.patch.object(auto_onboard, "_process_deal") as process_deal:
                processed, onboarded = auto_onboard.run_cycle(args)

            process_deal.assert_not_called()
            self.assertEqual(processed, 0)
            self.assertEqual(onboarded, 0)


if __name__ == "__main__":
    unittest.main()
