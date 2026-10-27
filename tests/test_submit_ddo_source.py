import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from cli.services.curio_market_client import CurioMarketClient, CurioMarketError
from cli.services.piece_set_commitment import PieceSet

# the click command of the same name shadows the module as an attribute of its package
MODULE = importlib.import_module("cli.commands.client.submit_ddo")

# two pieces of mainnet deal 21 (fileSize must imply pieceSize)
PIECES = [{"pieceCid": "baga6ea4seaqfmhhvyjyaqbmq4wdsjwlikxy2hs4zpoczr77lcthxcu5zsiupwgy", "pieceSize": 34359738368, "fileSize": 33288823369,
           "storagePath": "baga6ea4seaqfmhhvyjyaqbmq4wdsjwlikxy2hs4zpoczr77lcthxcu5zsiupwgy.car", "pieceType": "data"},
          {"pieceCid": "baga6ea4seaqkz62hf226ip23mccivz3zdxcm33t7bcpqrmcap2vetm5nibez4na", "pieceSize": 1048576, "fileSize": 534037,
           "storagePath": "baga6ea4seaqkz62hf226ip23mccivz3zdxcm33t7bcpqrmcap2vetm5nibez4na.car", "pieceType": "dag"}]
SOURCE = "https://healthy.example:443"


def curio_client():
    signer = MagicMock()
    signer.filecoin_address.return_value = "f410fclient"
    client = CurioMarketClient("https://curio.example", signer)
    client.sent = []
    client._request = lambda method, path, json_body=None: client.sent.append((method, path, json_body))
    return client


class CurioDataSourceTests(unittest.TestCase):
    def submit(self, **kwargs):
        client = curio_client()
        client.submit_ddo(provider="f02846602", piece_cid_v2="bafkzcib", duration_epochs=518400, identifier="ID",
                          notification_address="f410fadapter", notification_payload=b"\x01", **kwargs)
        return client.sent[0][2]["data"]

    def test_offline_is_the_default(self):
        data = self.submit()
        self.assertEqual(data["source_offline"], {})
        self.assertNotIn("source_http", data)

    def test_http_source_uses_curios_schema(self):
        data = self.submit(http_urls=["https://a/piece/x", "https://b/piece/x"])
        self.assertNotIn("source_offline", data)
        self.assertEqual(data["source_http"], {"urls": [{"url": "https://a/piece/x", "headers": {}, "priority": 0, "fallback": False},
                                                        {"url": "https://b/piece/x", "headers": {}, "priority": 1, "fallback": True}]})

    def test_preflight_requires_the_data_source_in_use(self):
        client = curio_client()
        client.get_products = lambda: ["ddo_v1", "retrieval_v1"]
        client.get_sources = lambda: ["offline"]
        client.preflight(None, "offline")
        with self.assertRaisesRegex(CurioMarketError, "does not support http data source"):
            client.preflight(None, "http")


class SubmitDdoSourceUrlTests(unittest.TestCase):
    def setUp(self):
        deal = SimpleNamespace(deal=SimpleNamespace(deal_id=21, provider_id="f02846602",
                                                    evidence_adapter_address=MagicMock(to_filecoin_address=lambda: "f410fadapter")),
                               data=SimpleNamespace(manifest_location="https://m.example/m.json", manifest_hash=PieceSet(PIECES).commitment()),
                               terms=SimpleNamespace(requested_size_bytes=PieceSet(PIECES).size_bytes, duration_epochs=518400))
        adapter = MagicMock()
        adapter.is_piece_accepted.return_value = False
        for p in (patch.object(MODULE.SelfUpdateService, "check_and_prompt", lambda manual: None),
                  patch.object(MODULE, "is_dry_run", lambda: False),
                  patch.object(MODULE, "PoRepMarketViewHelper", lambda: SimpleNamespace(get_deal_view=lambda deal_id: deal)),
                  patch.object(MODULE, "_validate_deal", lambda view: None),
                  patch.object(MODULE.commands_utils, "fetch_manifest", lambda *args, **kwargs: ([{"pieces": PIECES}], b"")),
                  patch.object(MODULE, "SectorEvidenceAdapter", lambda address: adapter),
                  patch.object(MODULE, "client_signer", MagicMock),
                  patch.object(MODULE, "piece_identifier", lambda deal_id, cid, signer: f"id-{cid[-6:]}")):
            p.start()
            self.addCleanup(p.stop)

    def test_print_only_lists_the_url_curio_downloads_each_piece_from(self):
        with patch.object(MODULE.commands_utils, "validate_and_parse_url", lambda url: None):
            result = CliRunner().invoke(MODULE.submit_ddo, ["21", "--print-only", "--source-url", f"{SOURCE}/"])

        self.assertEqual(result.exit_code, 0, result.output)
        for piece in PIECES:
            self.assertIn(f'"sourceUrl": "{SOURCE}/piece/{piece["pieceCid"]}"', result.output)

    def test_without_source_url_the_plan_has_no_urls(self):
        result = CliRunner().invoke(MODULE.submit_ddo, ["21", "--print-only"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn("sourceUrl", result.output)

    def test_private_source_url_is_refused(self):
        result = CliRunner().invoke(MODULE.submit_ddo, ["21", "--print-only", "--source-url", "http://127.0.0.1:8080"])
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("disallowed IP address", result.output)


if __name__ == "__main__":
    unittest.main()
