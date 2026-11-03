import json
import os
import stat
import subprocess
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import click

from cli.commands import repair_utils
from cli.services.contracts.evidence_adapter import EvidenceType
from cli.services.contracts.porep_market import PoRepMarketDealState, PoRepMarketDealType
from cli.services.piece_set_commitment import PieceSet
from cli.services.web3_service import EthAddress

# `retrieval-client fetch` flags common to LPR main and v1-maintenance (v1-maintenance has no --pay-token-address)
RETRIEVAL_CLIENT_FETCH_FLAGS = {f"--{flag}" for flag in (
    "cid", "cid-file", "dry-run", "expires-in-sec", "filpay-private-key", "filpay-private-key-env", "filpay-private-key-file",
    "manifest", "no-progress", "out-dir", "parallel", "pay-debug", "pay-payments-address", "pay-rpc-url", "sp-base-url",
    "verbose", "yes")}

# summary lines as printed by LPR's printFetchQuote (main and v1-maintenance)
PAID = """
Quote:
  CID           TYPE  SIZE      PRICE       SOURCE
  baga...wmq    paid  30.5 GiB  0.31 USDFC  http://127.0.0.1:8787

Total: 1.26 USDFC for 4 paid piece(s).
"""
MIXED = "Total: 0.62 USDFC for 2 paid piece(s); 3 free.\n"
FREE = "All 5 piece(s) are free; no Filecoin Pay charge required.\n"

PIECES = [{"pieceCid": "baga6ea4seaqfmhhvyjyaqbmq4wdsjwlikxy2hs4zpoczr77lcthxcu5zsiupwgy", "pieceSize": 34359738368, "fileSize": 33288823369},
          {"pieceCid": "baga6ea4seaqkz62hf226ip23mccivz3zdxcm33t7bcpqrmcap2vetm5nibez4na", "pieceSize": 1048576, "fileSize": 534037}]
OTHER_PIECES = PIECES[:1]
USDFC = "0x80B98d3aa09ffff255c3ba4A241111Ff1262F045"


def start(test: unittest.TestCase, *patches):
    for p in patches:
        p.start()
        test.addCleanup(p.stop)


class DryRunQuoteTests(unittest.TestCase):
    def test_quotes_are_parsed(self):
        for output, pieces, expected in ((PAID, 4, (Decimal("1.26"), 4, 0)), (MIXED, 5, (Decimal("0.62"), 2, 3)), (FREE, 5, (Decimal(0), 0, 5))):
            quote = repair_utils.parse_dry_run_quote(output, pieces)
            self.assertEqual((quote.total, quote.paid_pieces, quote.free_pieces), expected)

    def test_unexpected_quotes_are_refused(self):
        for output, pieces in ((PAID, 5), (FREE, 4), ("Quote:\n", 1), ("Total: abc USDFC for 1 paid piece(s).\n", 1)):
            with self.assertRaises(ValueError):
                repair_utils.parse_dry_run_quote(output, pieces)

    def fake_client(self, returncode=0, stdout=PAID, raise_timeout=False):
        calls = []

        def run(command, **kwargs):
            key = Path(command[command.index("--filpay-private-key-file") + 1])
            calls.append({"command": command, "env": kwargs["env"], "key_mode": stat.S_IMODE(key.stat().st_mode), "key": key})
            if raise_timeout:
                raise subprocess.TimeoutExpired(command, 1)
            return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="dataset incomplete: no usable source for CID baga")

        start(self, patch.object(repair_utils, "get_retrieval_client_path", lambda: "retrieval-client"),
              patch.object(repair_utils.subprocess, "run", run))
        return calls

    def test_quote_uses_a_throwaway_key_common_flags_and_no_secrets(self):
        calls = self.fake_client()

        with patch.dict(os.environ, {"CLIENT_PRIVATE_KEY": "placeholder-secret"}):
            quote = repair_utils.quote_retrieval("https://sp.example:8787", ["a", "b", "c", "d"])

        self.assertEqual(quote.total, Decimal("1.26"))
        call = calls[0]
        self.assertLessEqual({arg for arg in call["command"] if arg.startswith("--")}, RETRIEVAL_CLIENT_FETCH_FLAGS)
        self.assertIn("--dry-run", call["command"])
        self.assertEqual(call["key_mode"], 0o600)
        self.assertFalse(call["key"].exists())  # removed afterwards
        self.assertNotIn("CLIENT_PRIVATE_KEY", call["env"])

    def test_failed_timed_out_or_miscounted_quotes_mean_source_unavailable(self):
        for kwargs, message in (({"returncode": 1, "stdout": ""}, "no usable source"), ({"raise_timeout": True}, "timed out"),
                                ({"stdout": PAID}, "unexpected retrieval-client output")):
            with self.subTest(**kwargs):
                self.fake_client(**kwargs)
                with self.assertRaisesRegex(repair_utils.SourceUnavailable, message):
                    repair_utils.quote_retrieval("https://sp.example", ["a"])

    def test_private_source_addresses_are_refused_before_quoting(self):
        start(self, patch.object(repair_utils, "quote_retrieval", side_effect=AssertionError("must not quote a private address")),
              patch.dict(os.environ, {"ALLOW_PRIVATE_MANIFEST_URLS": ""}))
        source, reason = repair_utils.quote_source("http://127.0.0.1:8787", [{"pieceCid": "a"}])
        self.assertIsNone(source)
        self.assertIn("disallowed", reason)


class DiscoveryTests(unittest.TestCase):
    def test_http_base_from_multiaddr(self):
        for addr, base in (("/dns/mkt.lotus.dedyn.io/tcp/443/wss", "https://mkt.lotus.dedyn.io:443"),  # Curio market convention
                           ("/ip4/1.2.3.4/tcp/8787/http", "http://1.2.3.4:8787"),
                           ("/ip6/2001:db8::1/tcp/443/https", "https://[2001:db8::1]:443"),
                           ("/ip4/1.2.3.4/tcp/443/tls/http", "https://1.2.3.4:443"),
                           ("/ip4/1.2.3.4/tcp/24001", None),
                           ("/ip4/1.2.3.4/udp/443/quic-v1", None)):
            self.assertEqual(repair_utils.http_base_from_multiaddr(addr), base)

    def discover(self, cid_contact_ok):
        response = SimpleNamespace(ok=cid_contact_ok, text=json.dumps({"Addrs": ["/dns/ipni.example/tcp/8787/http", "/ip4/1.1.1.1/tcp/1"]}))
        start(self, patch.object(repair_utils, "Web3Service", lambda: SimpleNamespace(state_miner_info=lambda provider: {"PeerId": "12D3Koo"})),
              patch.object(repair_utils.requests, "get", lambda url, timeout: response),
              patch.object(repair_utils.CurioMarketDiscovery, "get_market_urls", lambda provider: ["https://chain.example"]))
        return repair_utils.discover_provider_http_bases(1234)

    def test_cid_contact_http_addresses_come_first(self):
        self.assertEqual(self.discover(cid_contact_ok=True), ["http://ipni.example:8787"])

    def test_on_chain_multiaddrs_are_the_fallback(self):
        self.assertEqual(self.discover(cid_contact_ok=False), ["https://chain.example"])


def view(deal_id, provider, evidence=EvidenceType.SECTOR_PLACEMENT, pieces=PIECES, state=PoRepMarketDealState.ACTIVE,
         deal_type=PoRepMarketDealType.PUBLIC, manifest_hash=None):
    piece_set = PieceSet(pieces)
    return SimpleNamespace(deal=SimpleNamespace(deal_id=deal_id, provider_id=provider, state=state, deal_type=deal_type,
                                                evidence_adapter_address=evidence),
                           data=SimpleNamespace(manifest_location=f"https://m.example/{deal_id}.json",
                                                manifest_hash=manifest_hash if manifest_hash is not None else piece_set.commitment()),
                           terms=SimpleNamespace(requested_size_bytes=piece_set.size_bytes))


class DatasetTests(unittest.TestCase):
    def setUp(self):
        # in these tests a deal's evidence_adapter_address holds its evidence type
        start(self, patch.object(repair_utils.commands_utils, "get_evidence_type", lambda address: address))
        self.manifests = {}
        start(self, patch.object(repair_utils.commands_utils, "fetch_manifest",
                                 lambda url, **kwargs: ([{"pieces": self.manifests[url][0]}], self.manifests[url][1])))

    def datacap_view(self, deal_id, provider, pieces=PIECES, served_raw=None, **kwargs):
        raw = json.dumps([{"pieces": pieces}]).encode()
        result = view(deal_id, provider, EvidenceType.VERIF_REG_CLAIMS, pieces,
                      manifest_hash=bytes(repair_utils.commands_utils.hash_manifest(raw)), **kwargs)
        self.manifests[result.data.manifest_location] = (pieces, served_raw if served_raw is not None else raw)
        return result

    def test_sector_placement_deals_use_their_on_chain_commitment(self):
        self.assertEqual(repair_utils.deal_dataset(view(1, "f01")), PieceSet(PIECES).commitment())

    def test_datacap_deals_are_identified_by_their_manifests_piece_set(self):
        self.assertEqual(repair_utils.deal_dataset(self.datacap_view(2, "f02")), PieceSet(PIECES).commitment())

    def test_datacap_deal_whose_manifest_changed_is_not_identified(self):
        self.assertIsNone(repair_utils.deal_dataset(self.datacap_view(3, "f03", served_raw=b'[{"pieces": []}]')))

    def test_healthy_sources_are_found_across_deal_types_and_free_ones_are_preferred(self):
        views = [view(1, "f0100"),  # excluded provider (the SP being repaired)
                 self.datacap_view(2, "f0200"),  # same dataset, DataCap deal, paid
                 view(3, "f0300", deal_type=PoRepMarketDealType.PRIVATE),  # LPR can't serve it to the new SP
                 view(4, "f0400", pieces=OTHER_PIECES),  # another dataset
                 view(5, "f0500", state=PoRepMarketDealState.ACCEPTED),  # not active
                 view(6, "f0600"),  # same dataset, sector placement deal, free
                 self.datacap_view(7, "f0700")]  # same dataset, not serving
        quotes = {"https://p0200": Decimal("0.02"), "https://p0600": Decimal(0)}
        probed = []

        def quote_source(base_url, pieces):
            probed.append(base_url)
            if base_url not in quotes:
                return None, "dataset incomplete: no usable source"
            paid = 0 if quotes[base_url] == 0 else 1
            quote = repair_utils.RetrievalQuote(total=quotes[base_url], paid_pieces=paid, free_pieces=len(pieces) - paid)
            return repair_utils.RetrievalSource(base_url=base_url, quote=quote), "ok"

        start(self, patch.object(repair_utils, "PoRepMarketViewHelper", lambda: SimpleNamespace(get_deal_views=lambda: views)),
              patch.object(repair_utils.commands_utils, "get_deal_claim_ids", lambda deal: [1]),
              patch.object(repair_utils, "discover_provider_http_bases", lambda provider: [f"https://p{provider[1:]}"]),
              patch.object(repair_utils, "quote_source", quote_source))

        source = repair_utils.find_healthy_source(PIECES, exclude_provider_ids={"f0100"})

        self.assertEqual((source.deal_id, source.provider_id, source.is_free()), (6, "f0600", True))
        self.assertEqual(probed, ["https://p0200", "https://p0600", "https://p0700"])

    def test_datacap_deal_without_claims_is_skipped(self):
        start(self, patch.object(repair_utils, "PoRepMarketViewHelper", lambda: SimpleNamespace(get_deal_views=lambda: [self.datacap_view(2, "f0200")])),
              patch.object(repair_utils.commands_utils, "get_deal_claim_ids", lambda deal: []))
        with self.assertRaisesRegex(click.ClickException, "No healthy SP"):
            repair_utils.find_healthy_source(PIECES, exclude_provider_ids=set())


class PayeeAndTokenTests(unittest.TestCase):
    def setUp(self):
        self.code = b""
        start(self, patch.object(repair_utils, "Web3Service", lambda: SimpleNamespace(
            w3=lambda: SimpleNamespace(eth=SimpleNamespace(get_code=lambda address: self.code)), get_chain_id=lambda: 314)),
              patch.object(repair_utils, "SPRegistry", lambda: SimpleNamespace(
                  get_provider_view=lambda provider: SimpleNamespace(payee_address="0x" + "22" * 20))))

    def deal(self, payee, token=USDFC):
        return SimpleNamespace(deal=SimpleNamespace(deal_id=9, provider_id="f01"), payment=SimpleNamespace(payee=payee, payment_token=token))

    def test_the_deal_payee_else_the_registry_payee(self):
        self.assertEqual(repair_utils.resolve_repair_payee(self.deal("0x" + "11" * 20)), EthAddress("0x" + "11" * 20))
        self.assertEqual(repair_utils.resolve_repair_payee(self.deal("0x" + "00" * 20)), EthAddress("0x" + "22" * 20))

    def test_contract_payee_is_refused(self):
        self.code = b"\x60\x80"
        with self.assertRaisesRegex(click.ClickException, "is a contract"):
            repair_utils.resolve_repair_payee(self.deal("0x" + "11" * 20))

    def test_only_usdfc_deals_can_be_repaired(self):
        with patch.dict(os.environ, {"SP_PROXY_PAY_TOKEN_ADDRESS": ""}):
            self.assertEqual(repair_utils.repair_payment_token(self.deal("0x" + "11" * 20)), EthAddress(USDFC))
            with self.assertRaisesRegex(click.ClickException, "only USDFC deals can be repaired"):
                repair_utils.repair_payment_token(self.deal("0x" + "11" * 20, token="0x" + "33" * 20))

    def test_usdfc_override_for_devnets(self):
        with patch.dict(os.environ, {"SP_PROXY_PAY_TOKEN_ADDRESS": "0x" + "44" * 20}):
            self.assertEqual(repair_utils.usdfc_token(), EthAddress("0x" + "44" * 20))


class ProcessHygieneTests(unittest.TestCase):
    def test_child_env_drops_the_clis_secrets(self):
        with patch.dict(os.environ, {"CLIENT_PRIVATE_KEY": "x", "SP_LOTUS_TOKEN": "y", "SP_REGISTRY_DATABASE_URL": "z", "FILPAY_PRIVATE_KEY": "k"}):
            env = repair_utils.child_env(keep=("FILPAY_PRIVATE_KEY",), EXTRA="1")
        self.assertFalse({"CLIENT_PRIVATE_KEY", "SP_LOTUS_TOKEN", "SP_REGISTRY_DATABASE_URL"} & set(env))
        self.assertEqual((env["FILPAY_PRIVATE_KEY"], env["EXTRA"]), ("k", "1"))

    @unittest.skipUnless(os.name == "posix", "POSIX permissions")
    def test_key_files_must_be_owner_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            key_file = Path(tmp) / "payee.key"
            key_file.write_text("secret-key-material", encoding="utf-8")
            key_file.chmod(0o600)
            repair_utils.ensure_secret_file(key_file, "payee key file")

            for mode in (0o640, 0o644, 0o604):
                key_file.chmod(mode)
                with self.assertRaises(click.ClickException) as error:
                    repair_utils.ensure_secret_file(key_file, "payee key file")
                self.assertNotIn("secret-key-material", error.exception.message)


if __name__ == "__main__":
    unittest.main()
