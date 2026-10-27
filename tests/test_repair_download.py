import importlib
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import click
from click.testing import CliRunner

from cli.commands.repair_funding import FundingHistoryUnavailable, RepairFunding
from cli.commands.repair_utils import RetrievalQuote, RetrievalSource, SourceUnavailable
from cli.services.cid_converter import piece_cid_v1_to_v2
from cli.services.contracts.evidence_adapter import EvidenceType
from cli.services.contracts.porep_market import PoRepMarketDealState
from cli.services.piece_set_commitment import PieceSet
from tests.test_repair_utils import RETRIEVAL_CLIENT_FETCH_FLAGS

download = importlib.import_module("cli.commands.sp._repair_download")
onboard = importlib.import_module("cli.commands.sp.onboard_data")

USDFC = 10 ** 18
PIECES = [{"pieceCid": "baga6ea4seaqfmhhvyjyaqbmq4wdsjwlikxy2hs4zpoczr77lcthxcu5zsiupwgy", "pieceSize": 34359738368, "fileSize": 33288823369,
           "storagePath": "data/baga6ea4seaqfmhhvyjyaqbmq4wdsjwlikxy2hs4zpoczr77lcthxcu5zsiupwgy.car"},
          {"pieceCid": "baga6ea4seaqkz62hf226ip23mccivz3zdxcm33t7bcpqrmcap2vetm5nibez4na", "pieceSize": 1048576, "fileSize": 534037,
           "storagePath": "baga6ea4seaqkz62hf226ip23mccivz3zdxcm33t7bcpqrmcap2vetm5nibez4na.car"}]
DEAL = SimpleNamespace(deal=SimpleNamespace(deal_id=21, provider_id="f02846602", client_address="0xClient", proposed_at_epoch=100,
                                            state=PoRepMarketDealState.ACCEPTED, evidence_adapter_address="0xAdapter"),
                       data=SimpleNamespace(manifest_location="https://m.example/m.json", manifest_hash=PieceSet(PIECES).commitment()),
                       terms=SimpleNamespace(requested_size_bytes=PieceSet(PIECES).size_bytes))
SOURCE = "https://healthy.example"
PAID = RetrievalQuote(total=Decimal("1.5"), paid_pieces=2, free_pieces=0)
FREE = RetrievalQuote(total=Decimal(0), paid_pieces=0, free_pieces=2)
FUNDED = RepairFunding(deposited=2 * USDFC, spent=0)


class DownloadTestCase(unittest.TestCase):
    def start(self, *patches):
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def setUp(self):
        self.out_dir = Path(tempfile.mkdtemp()).resolve()
        self.runs = []

        def fake_run(command, **kwargs):  # retrieval-client stand-in: writes <pieceCid>.car files into --out-dir
            key_file = command[command.index("--filpay-private-key-file") + 1] if "--filpay-private-key-file" in command else None
            self.runs.append({"command": command, "env": kwargs.get("env"), "key_file": key_file,
                              "key_existed": key_file is not None and Path(key_file).exists()})
            out_dir = Path(command[command.index("--out-dir") + 1])
            for cid in Path(command[command.index("--cid-file") + 1]).read_text(encoding="utf-8").split():
                (out_dir / f"{cid}.car").write_bytes(b"car")

        self.start(patch.object(download, "get_retrieval_client_path", lambda: "retrieval-client"),
                   patch.object(download.subprocess, "run", side_effect=fake_run),
                   patch.object(download.utils, "confirm", lambda *args, **kwargs: True),
                   patch.object(download, "FileCoinPay", lambda: SimpleNamespace(address=lambda: "0xPay")),
                   patch.dict(download.os.environ, {"RPC_URL": "https://rpc.example"}))

    def use(self, quote, funding=FUNDED, payee_key_ok=True):
        events = []

        def fake_quote(base_url, cids):
            events.append("quote")
            if isinstance(quote, Exception):
                raise quote
            return quote

        def fake_funding(token, client, payee, since):
            events.append("funding")
            if isinstance(funding, Exception):
                raise funding
            return funding

        def fake_payee_key(deal, key_file):
            events.append("key")
            if not payee_key_ok:
                raise click.ClickException("Payee key address does not match")

        token = SimpleNamespace(address=lambda: "0xUSDFC", decimals=lambda: 18, symbol=lambda: "USDFC")
        self.start(patch.object(download, "quote_retrieval", fake_quote),
                   patch.object(download, "get_repair_funding", fake_funding),
                   patch.object(download, "_ensure_payee_key", fake_payee_key),
                   patch.object(download, "repair_payment_token", lambda deal: "0xUSDFC"),
                   patch.object(download, "ERC20Contract", lambda address: token),
                   patch.object(download, "resolve_repair_payee", lambda deal: "0xPayee"))
        return events

    def download(self, allow_unfunded_retrieval=False, pieces=PIECES):
        with click.Context(onboard.onboard_data) as ctx:
            download.download_with_lpr(ctx, DEAL, pieces, SOURCE, self.out_dir, True, "/sp/payee.key", allow_unfunded_retrieval)


class FundingGateTests(DownloadTestCase):
    def test_covered_quote_downloads_with_the_payee_key(self):
        events = self.use(PAID)
        self.download()
        self.assertEqual(events, ["quote", "key", "funding"])
        self.assertTrue(self.runs[0]["key_file"].endswith("/sp/payee.key"))

    def test_short_funding_waits_for_the_client(self):
        self.use(PAID, RepairFunding(deposited=USDFC, spent=0))
        with self.assertRaisesRegex(click.ClickException, r"Waiting for client funding: quote 1\.5 USDFC, available 1 USDFC, short 0\.5 USDFC") as error:
            self.download()
        self.assertIn("client pay-repair-retrieval 21", error.exception.message)
        self.assertEqual(self.runs, [])

    def test_spending_beyond_the_deposits_counts_as_nothing_available(self):
        self.use(PAID, RepairFunding(deposited=USDFC, spent=3 * USDFC))
        with self.assertRaisesRegex(click.ClickException, r"available 0 USDFC, short 1\.5 USDFC"):
            self.download()

    def test_unverifiable_funding_fails_closed(self):
        self.use(PAID, FundingHistoryUnavailable("lookback limit"))
        with self.assertRaisesRegex(click.ClickException, "Could not check the client's repair funding.*lookback limit"):
            self.download()
        self.assertEqual(self.runs, [])

    def test_short_or_unverifiable_funding_can_be_overridden(self):
        for funding in (RepairFunding(deposited=0, spent=0), FundingHistoryUnavailable("lookback limit")):
            with self.subTest(funding=funding):
                self.runs.clear()
                self.use(PAID, funding)
                self.download(allow_unfunded_retrieval=True)
                self.assertEqual(len(self.runs), 1)

    def test_wrong_payee_key_stops_before_paying(self):
        events = self.use(PAID, payee_key_ok=False)
        with self.assertRaisesRegex(click.ClickException, "does not match"):
            self.download()
        self.assertEqual((events, self.runs), (["quote", "key"], []))


class LprDownloadTests(DownloadTestCase):
    def test_free_download_needs_no_payee_key(self):
        events = self.use(FREE)
        self.download()
        self.assertEqual(events, ["quote"])
        run = self.runs[0]
        self.assertNotIn("/sp/payee.key", run["key_file"])
        self.assertTrue(run["key_existed"])
        self.assertFalse(Path(run["key_file"]).exists())  # throwaway key removed afterwards

    def test_only_flags_every_retrieval_client_build_has_and_no_cli_secrets(self):
        self.use(PAID)
        with patch.dict(download.os.environ, {"CLIENT_PRIVATE_KEY": "placeholder-secret"}):
            self.download()
        command = self.runs[0]["command"]
        self.assertLessEqual({arg for arg in command if arg.startswith("--")}, RETRIEVAL_CLIENT_FETCH_FLAGS)
        self.assertNotIn("CLIENT_PRIVATE_KEY", self.runs[0]["env"])

    def test_pieces_are_moved_to_their_manifest_paths(self):
        self.use(FREE)
        self.download()
        for piece in PIECES:
            self.assertTrue((self.out_dir / piece["storagePath"]).is_file())
        self.assertFalse((self.out_dir / f"{PIECES[0]['pieceCid']}.car").exists())

    def test_storage_path_outside_the_output_dir_is_refused_before_quoting(self):
        events = self.use(PAID)
        with self.assertRaisesRegex(click.ClickException, "Invalid manifest piece storagePath"):
            self.download(pieces=[{**PIECES[0], "storagePath": "../escape.car"}])
        self.assertEqual((events, self.runs), ([], []))

    def test_unavailable_source_stops_before_any_payment(self):
        self.use(SourceUnavailable("dataset incomplete"))
        with self.assertRaisesRegex(click.ClickException, "cannot serve the data: dataset incomplete"):
            self.download()
        self.assertEqual(self.runs, [])


class OnboardDataLprTests(DownloadTestCase):
    def test_lpr_finds_the_healthy_source_and_names_pieces_by_cid_v2(self):
        self.use(FREE)
        adapter = MagicMock()
        adapter.is_piece_accepted.return_value = False
        found = []
        self.start(patch.object(onboard.SelfUpdateService, "check_and_prompt", lambda manual: None),
                   patch.object(onboard, "get_retrieval_client_path", lambda: "retrieval-client"),
                   patch.object(onboard, "PoRepMarketViewHelper", lambda: SimpleNamespace(get_deal_view=lambda deal_id: DEAL)),
                   patch.object(onboard.commands_utils, "fetch_manifest", lambda *args, **kwargs: ([{"pieces": PIECES}], b"")),
                   patch.object(onboard.commands_utils, "get_evidence_type", lambda address: EvidenceType.SECTOR_PLACEMENT),
                   patch.object(onboard, "SectorEvidenceAdapter", lambda address: adapter),
                   patch.object(onboard.commands_utils, "validate_and_parse_url",
                                side_effect=lambda url: __import__("urllib.parse").parse.urlparse(url)),
                   patch.object(onboard, "find_healthy_source", lambda pieces, exclude: found.append(exclude) or RetrievalSource(
                       base_url=SOURCE, quote=FREE, deal_id=8, provider_id="f08240")))

        result = CliRunner().invoke(onboard.onboard_data, ["21", "--output-dir", str(self.out_dir), "--downloader", "lpr", "--no-summary"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(found, [{"f02846602"}])  # the deal's own SP is never its source
        self.assertEqual(self.runs[0]["command"][self.runs[0]["command"].index("--sp-base-url") + 1], SOURCE)
        for piece in PIECES:
            v2_name = f"{piece_cid_v1_to_v2(piece['pieceCid'], piece['fileSize'])}.car"
            self.assertTrue((self.out_dir / piece["storagePath"]).with_name(v2_name).is_file())


if __name__ == "__main__":
    unittest.main()
