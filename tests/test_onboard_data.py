import importlib
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from cli.commands.sp.onboard_data import onboard_data
from cli.services.cid_converter import piece_cid_v1_to_v2
from cli.services.contracts.evidence_adapter import EvidenceType
from cli.services.contracts.porep_market import PoRepMarketDealState
from cli.services.piece_set_commitment import PieceSet

# the click command of the same name shadows the module as an attribute of its package
MODULE = importlib.import_module("cli.commands.sp.onboard_data")

PIECES = [{"pieceCid": cid, "pieceSize": size, "fileSize": size, "storagePath": f"{cid}.car", "pieceType": kind}
          for cid, size, kind in (("baga6ea4seaqkz62hf226ip23mccivz3zdxcm33t7bcpqrmcap2vetm5nibez4na", 1048576, "dag"),
                                  ("baga6ea4seaqa3s7p42ehf2ql6qvnwb7bx5q4ki2hncmpf7zljsmdgugknm724fi", 34359738368, "data"),
                                  ("baga6ea4seaqcs4qzqm5im2cotkfqmtaw44orcq6ola4v2dsmagq3alqpdv7ymoy", 34359738368, "data"))]
MANIFEST = [{"pieces": PIECES}]
DEAL_ID = 21
SOURCE = "https://source.example"


def deal_view(manifest_hash=None):
    piece_set = PieceSet(PIECES)
    return SimpleNamespace(
        deal=SimpleNamespace(deal_id=DEAL_ID, state=PoRepMarketDealState.ACCEPTED, evidence_adapter_address="0xAdapter"),
        data=SimpleNamespace(manifest_location="https://manifest.example/m.json",
                             manifest_hash=manifest_hash if manifest_hash is not None else piece_set.commitment()),
        terms=SimpleNamespace(requested_size_bytes=piece_set.size_bytes))


class OnboardDataEvidenceTypeTests(unittest.TestCase):
    def setUp(self):
        self.out_dir = tempfile.mkdtemp()
        self.aria2_inputs = []

        def fake_run(command, **kwargs):
            if "-i" in command:
                aria2_input = Path(command[command.index("-i") + 1]).read_text(encoding="utf-8")
                self.aria2_inputs.append(aria2_input)
                # aria2c stand-in: write each requested file
                for out, directory in zip(re.findall(r"^  out=(.+)$", aria2_input, re.MULTILINE), re.findall(r"^  dir=(.+)$", aria2_input, re.MULTILINE)):
                    (Path(directory) / out).write_bytes(b"car")
            self.aria2_env = kwargs.get("env")

        patches = [
            patch.object(MODULE.SelfUpdateService, "check_and_prompt", lambda manual: None),
            patch.object(MODULE, "_get_aria2c_path", lambda: "aria2c"),
            patch.object(MODULE.subprocess, "run", side_effect=fake_run),
            patch.object(MODULE.utils, "confirm", lambda *args, **kwargs: True),
            patch.object(MODULE, "PoRepMarket", lambda: SimpleNamespace(get_sector_size_bytes=lambda: 34359738368)),
            patch.object(MODULE.commands_utils, "validate_and_parse_url", side_effect=lambda url: __import__("urllib.parse").parse.urlparse(url)),
            patch.object(MODULE.commands_utils, "fetch_manifest", lambda *args, **kwargs: (MANIFEST, b"")),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def use_deal(self, view, evidence_type):
        for p in (patch.object(MODULE, "PoRepMarketViewHelper", lambda: SimpleNamespace(get_deal_view=lambda deal_id: view)),
                  patch.object(MODULE.commands_utils, "get_evidence_type", lambda address: evidence_type)):
            p.start()
            self.addCleanup(p.stop)

    def use_accepted(self, accepted_indexes):
        adapter = MagicMock()
        adapter.is_piece_accepted.side_effect = lambda deal_id, index: index in accepted_indexes
        p = patch.object(MODULE, "SectorEvidenceAdapter", lambda address: adapter)
        p.start()
        self.addCleanup(p.stop)

    def run_onboard(self, *extra):
        return CliRunner().invoke(onboard_data, [str(DEAL_ID), "--output-dir", self.out_dir, "--host", SOURCE, "--port", "443",
                                                 "--no-summary", *extra])

    def test_sector_placement_downloads_only_pieces_not_placed(self):
        self.use_deal(deal_view(), EvidenceType.SECTOR_PLACEMENT)
        self.use_accepted({0})
        result = self.run_onboard()

        # piece indexes follow the piece set's canonical order, not the manifest's
        placed_cid = next(row.piece_cid for row in PieceSet(PIECES).rows if row.index == 0)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(len(self.aria2_inputs), 1)
        urls = [line for line in self.aria2_inputs[0].splitlines() if line.startswith("https://")]
        self.assertEqual(urls, [f"{SOURCE}:443/piece/{piece['pieceCid']}" for piece in PIECES if piece["pieceCid"] != placed_cid])
        self.assertIn("Skipping download of 1 already placed pieces", result.output)
        self.assertNotIn("ARIA2C_CLAIM_ALLOCATIONS_SOFTWARE", self.aria2_env or {})

    def test_sector_placement_with_every_piece_placed_downloads_nothing(self):
        self.use_deal(deal_view(), EvidenceType.SECTOR_PLACEMENT)
        self.use_accepted({0, 1, 2})
        result = self.run_onboard()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("All 3 pieces of deal ID 21 are placed", result.output)
        self.assertEqual(self.aria2_inputs, [])

    def test_sector_placement_refuses_a_manifest_the_deal_was_not_proposed_with(self):
        self.use_deal(deal_view(manifest_hash=b"\x01" * 32), EvidenceType.SECTOR_PLACEMENT)
        self.use_accepted(set())
        result = self.run_onboard()

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("does not match deal ID 21 manifest hash", result.output)
        self.assertEqual(self.aria2_inputs, [])

    def test_downloaded_pieces_are_also_named_by_piece_cid_v2(self):
        self.use_deal(deal_view(), EvidenceType.SECTOR_PLACEMENT)
        self.use_accepted(set())
        result = self.run_onboard()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Named 3 downloaded piece(s) also by piece CID v2", result.output)

        for piece in PIECES:
            v1_file = Path(self.out_dir) / piece["storagePath"]
            v2_file = Path(self.out_dir) / f"{piece_cid_v1_to_v2(piece['pieceCid'], piece['fileSize'])}.car"
            self.assertTrue(v2_file.is_file())
            self.assertTrue(os.path.samefile(v1_file, v2_file))


    def test_rerun_keeps_existing_piece_cid_v2_names(self):
        self.use_deal(deal_view(), EvidenceType.SECTOR_PLACEMENT)
        self.use_accepted(set())
        self.assertEqual(self.run_onboard().exit_code, 0)

        result = self.run_onboard()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn("Named", result.output)
        self.assertNotIn("WARNING", result.output)

    def test_unrelated_file_with_the_piece_cid_v2_name_is_left_alone(self):
        self.use_deal(deal_view(), EvidenceType.SECTOR_PLACEMENT)
        self.use_accepted(set())
        piece = PIECES[0]
        v2_file = Path(self.out_dir) / f"{piece_cid_v1_to_v2(piece['pieceCid'], piece['fileSize'])}.car"
        v2_file.write_bytes(b"something else")

        result = self.run_onboard()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(f"WARNING: {v2_file.resolve()} already exists", result.output)
        self.assertEqual(v2_file.read_bytes(), b"something else")
        self.assertIn("Named 2 downloaded piece(s)", result.output)


class PieceCidV2NameTests(unittest.TestCase):
    def test_name_matches_what_curio_requests(self):
        # the DAG piece of mainnet deal 21, and the piece CID v2 its SP's Curio requested for it
        piece = {"pieceCid": "baga6ea4seaqkz62hf226ip23mccivz3zdxcm33t7bcpqrmcap2vetm5nibez4na", "fileSize": 534037,
                 "storagePath": "baga6ea4seaqkz62hf226ip23mccivz3zdxcm33t7bcpqrmcap2vetm5nibez4na.car"}
        out_dir = Path(tempfile.mkdtemp()).resolve()
        (out_dir / piece["storagePath"]).write_bytes(b"car")

        self.assertEqual(MODULE._link_piece_cid_v2_names([piece], out_dir), 1)
        self.assertTrue((out_dir / "bafkzcibe5pzr4d5m7nds5npeh5nwbbek454r3rgn5z7qrhyiwbah5ksjwowuasm6gq.car").is_file())

    def test_pieces_outside_the_output_dir_or_not_downloaded_are_skipped(self):
        out_dir = Path(tempfile.mkdtemp()).resolve()
        pieces = [{"pieceCid": PIECES[1]["pieceCid"], "fileSize": 1, "storagePath": "../escape.car"},
                  {"pieceCid": PIECES[2]["pieceCid"], "fileSize": 1, "storagePath": "missing.car"}]

        self.assertEqual(MODULE._link_piece_cid_v2_names(pieces, out_dir), 0)
        self.assertEqual(list(out_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
