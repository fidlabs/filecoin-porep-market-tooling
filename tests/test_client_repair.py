import importlib
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import click
from click.testing import CliRunner

from cli.commands.repair_utils import RetrievalQuote, RetrievalSource
from cli.services.contracts.porep_market import PoRepMarketDealState

# the click command of the same name shadows the module as an attribute of its package
repair_module = importlib.import_module("cli.commands.client.repair")

CLIENT = "0xClient"
MANIFEST = "https://m.example/manifest.json"
SIZE = 311386177536


def view(deal_id, state, provider_id="f02", proposed_at_epoch=2000, dataset=b"pieces", marker: int | None = 10, size=SIZE):
    location = MANIFEST if marker is None else f"{MANIFEST}#fcss-repair-of={marker}"
    return SimpleNamespace(deal=SimpleNamespace(deal_id=deal_id, state=PoRepMarketDealState[state], provider_id=provider_id,
                                                proposed_at_epoch=proposed_at_epoch, client_address=CLIENT, deal_type="PUBLIC"),
                           data=SimpleNamespace(manifest_location=location, dataset=dataset),
                           terms=SimpleNamespace(requested_size_bytes=size))


OLD = view(10, "ACTIVE", provider_id="f01", proposed_at_epoch=1000, marker=None)


def source(free: bool) -> RetrievalSource:
    quote = RetrievalQuote(total=Decimal(0) if free else Decimal("1.5"), paid_pieces=0 if free else 11, free_pieces=11 if free else 0)
    return RetrievalSource(base_url="https://healthy.example", quote=quote, deal_id=8, provider_id="f08240")


class RepairTestCase(unittest.TestCase):
    def start(self, *patches):
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def chain(self, *views):
        by_id = {v.deal.deal_id: v for v in views}
        self.start(patch.object(repair_module, "client_address", lambda: CLIENT),
                   patch.object(repair_module.commands_utils, "get_client_deals", lambda client: [v.deal for v in views]),
                   patch.object(repair_module, "PoRepMarketViewHelper", lambda: SimpleNamespace(get_deal_view=lambda deal_id: by_id[deal_id])),
                   patch.object(repair_module, "deal_dataset", lambda v: v.data.dataset))
        return by_id

    def prompts(self):
        asked = []

        def fake_confirm(text, default=False, abort=False, **kwargs):
            asked.append((text, default))
            if abort:
                raise click.Abort()
            return False

        self.start(patch.object(repair_module.utils, "confirm", fake_confirm))
        return asked


class FindRepairDealTests(RepairTestCase):
    def test_resumes_the_latest_pending_deal_marked_for_this_repair(self):
        self.chain(OLD, view(11, "PROPOSED"), view(12, "ACCEPTED"), view(13, "REJECTED"))
        self.assertEqual(repair_module._find_repair_deal(OLD).deal.deal_id, 12)

    def test_marked_active_deal_means_the_repair_is_done(self):
        self.chain(OLD, view(11, "ACTIVE"), view(12, "ACCEPTED"))
        self.assertEqual(repair_module._find_repair_deal(OLD).deal.deal_id, 11)

    def test_ignores_deals_that_are_not_this_repair(self):
        for other in (view(11, "ACCEPTED", provider_id="f01"),  # the repaired deal's own SP
                      view(11, "ACCEPTED", dataset=b"other"),  # another dataset
                      view(11, "ACCEPTED", size=1),  # another size, so another dataset
                      view(11, "ACCEPTED", marker=12),  # the repair of another deal
                      view(11, "REJECTED")):
            with self.subTest(other=other):
                self.chain(OLD, other)
                self.assertIsNone(repair_module._find_repair_deal(OLD))

    def test_pending_unmarked_original_copy_is_never_picked(self):
        self.chain(OLD, view(11, "ACCEPTED", marker=None))
        asked = self.prompts()
        with self.assertRaises(click.Abort):
            repair_module._find_repair_deal(OLD)
        text, default = asked[0]
        self.assertIn("--repair-deal", text)
        self.assertIs(default, False)

    def test_after_proposing_only_marked_deals_count(self):
        self.chain(OLD, view(11, "ACCEPTED", marker=None))
        self.prompts()
        self.assertIsNone(repair_module._find_repair_deal(OLD, marked_only=True))


class GivenRepairDealTests(RepairTestCase):
    def test_marked_deal_needs_no_confirmation(self):
        self.chain(OLD, view(11, "ACCEPTED"))
        self.assertEqual(repair_module._given_repair_deal(OLD, 11).deal.deal_id, 11)

    def test_unmarked_deal_needs_a_confirmation_defaulting_to_no(self):
        self.chain(OLD, view(11, "ACCEPTED", marker=None))
        self.start(patch.object(repair_module, "resolve_repair_payee", lambda v: "0xPayee"))
        asked = self.prompts()
        with self.assertRaises(click.Abort):
            repair_module._given_repair_deal(OLD, 11)
        self.assertIs(asked[0][1], False)

    def test_deal_that_cannot_be_this_repair_is_refused(self):
        for other, message in ((view(11, "ACCEPTED", provider_id="f01"), "own provider"),
                               (view(11, "ACCEPTED", dataset=b"other"), "another dataset"),
                               (view(11, "ACCEPTED", marker=12), "repair of deal ID 12"),
                               (view(11, "REJECTED"), "in state")):
            with self.subTest(message=message):
                self.chain(OLD, other)
                with self.assertRaisesRegex(click.ClickException, message):
                    repair_module._given_repair_deal(OLD, 11)


class TermsTests(unittest.TestCase):
    def test_old_terms_convert_back_exactly(self):
        with patch.object(repair_module, "ERC20Contract", lambda address: SimpleNamespace(decimals=lambda: 18)), \
                patch.object(repair_module, "PoRepMarket", lambda: SimpleNamespace(get_sector_size_bytes=lambda: 32 * 2 ** 30)):
            old = SimpleNamespace(deal=SimpleNamespace(deal_id=2), terms=SimpleNamespace(duration_epochs=518400),
                                  payment=SimpleNamespace(payment_token="0xUSDFC", price_per_32_gib_per_month=125 * 10 ** 15))
            self.assertEqual(repair_module._old_price_per_tib(old), 4.0)
            self.assertEqual(repair_module._old_duration_months(old), 6)

            old.terms.duration_epochs += 1
            with self.assertRaisesRegex(click.UsageError, "--duration-months"):
                repair_module._old_duration_months(old)

    def test_new_repair_deal_is_proposed_with_the_marker(self):
        proposed = []
        old = SimpleNamespace(deal=SimpleNamespace(deal_id=10, provider_id="f01", deal_type="PUBLIC"),
                              data=SimpleNamespace(manifest_location=MANIFEST),
                              required_slis=SimpleNamespace(retrievability_bps=9050, bandwidth_bytes_per_second=125_001, latency_ms=0, indexing_pct=0),
                              payment=SimpleNamespace(payment_token="0xUSDFC"))
        with patch.object(repair_module.commands_utils, "fetch_manifest", lambda url, **kwargs: ([{"pieces": []}], b"")), \
                patch.object(repair_module, "find_healthy_source", lambda *args: source(free=True)), \
                patch.object(repair_module, "client_signer", lambda: None), \
                patch.object(repair_module.commands_utils, "propose_deal", lambda signer, url, *args: proposed.append((url, args))):
            self.assertTrue(repair_module._propose_repair_deal(old, None, 4.0, 6).is_free())

        url, args = proposed[0]
        self.assertEqual(url, f"{MANIFEST}#fcss-repair-of=10")
        self.assertEqual(args[:2], (91, 2))  # SLIs rounded up: never ask for less than the repaired deal


class RepairFlowTests(RepairTestCase):
    def flow(self, state_after_wait: str, found=None, retrieval_source=None):
        new = view(11, "PROPOSED")
        self.chain(OLD, new)
        OLD.payment = SimpleNamespace(payment_token="0xUSDFC")
        steps = []
        self.start(patch.object(repair_module.SelfUpdateService, "check_and_prompt", lambda manual: None),
                   patch.object(repair_module._repair, "ensure_repairable", lambda v: None),
                   patch.object(repair_module, "ensure_usdfc", lambda token, subject: None),
                   patch.object(repair_module, "_find_repair_deal", lambda old, marked_only=False: found or new),
                   patch.object(repair_module, "_wait_for_acceptance", lambda deal_id, minutes: view(deal_id, state_after_wait)),
                   patch.object(repair_module._repair, "pay_repair_retrieval",
                                lambda *args, **kwargs: steps.append(("pay", args[0], kwargs["covered_is_done"])) or (retrieval_source or source(True))),
                   patch.object(repair_module.init_deal, "callback", lambda deal_id: steps.append(("init", deal_id))),
                   patch.object(repair_module.submit_ddo, "callback", lambda deal_id, source_url=None, **kwargs: steps.append(("submit", deal_id, source_url))),
                   patch.object(repair_module.deposit_for_deals, "callback", lambda deal_id=None, months=1: steps.append(("deposit", deal_id))))
        return steps

    @staticmethod
    def run_repair():
        return CliRunner().invoke(repair_module.repair, ["10"])

    def test_free_source_lets_curio_download_the_data(self):
        steps = self.flow("ACCEPTED", retrieval_source=source(free=True))
        result = self.run_repair()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(steps, [("pay", 11, True), ("init", 11), ("submit", 11, "https://healthy.example"), ("deposit", 11)])
        self.assertIn("Curio downloads the data from https://healthy.example itself", result.output)

    def test_paid_source_is_downloaded_by_the_new_sp(self):
        steps = self.flow("ACCEPTED", retrieval_source=source(free=False))
        result = self.run_repair()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(steps, [("pay", 11, True), ("init", 11), ("submit", 11, None), ("deposit", 11)])
        self.assertIn("sp onboard-data 11 --downloader lpr", result.output)

    def test_unaccepted_repair_deal_stops_without_paying(self):
        steps = self.flow("PROPOSED")
        result = self.run_repair()
        self.assertEqual(steps, [])
        self.assertIn("client repair 10", result.output)

    def test_rejected_repair_deal_asks_to_rerun(self):
        steps = self.flow("REJECTED")
        result = self.run_repair()
        self.assertEqual(result.exit_code, 1)
        self.assertIn("propose a new one", result.output)
        self.assertEqual(steps, [])

    def test_done_repair_is_reported_without_paying_again(self):
        steps = self.flow("ACCEPTED", found=view(11, "ACTIVE"))
        result = self.run_repair()
        self.assertEqual(steps, [])
        self.assertIn("repair deal ID 11", result.output)


if __name__ == "__main__":
    unittest.main()
