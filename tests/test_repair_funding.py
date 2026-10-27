import unittest
from types import SimpleNamespace
from unittest.mock import patch

import click

from cli.commands import repair_funding
from cli.commands.client import _repair
from cli.services.contracts.porep_market import PoRepMarketDealState

TOKEN, PAYEE, CLIENT = "0xToken", "0xPayee", "0xClient"
DECIMALS, COST = 18, 5 * 10 ** 18
MANIFEST = "https://manifests.example/m.json"


class FakeFileCoinPay:
    def __init__(self, deposits_by_block: dict[int, int], max_range: int | None = None, fail_before: int | None = None,
                 payments_by_block: dict[int, tuple[int, int]] | None = None, rail_ids: list[int] | None = None):
        self.deposits_by_block = deposits_by_block
        self.payments_by_block = payments_by_block or {}  # block -> (rail ID, gross amount)
        self.rail_ids = rail_ids or []
        self.max_range = max_range
        self.fail_before = fail_before
        self.ranges = []

    def _check_range(self, from_block, to_block):
        if self.fail_before is not None and from_block < self.fail_before:
            raise RuntimeError("bad tipset height: lookbacks of more than 24h0m0s are disallowed")
        if self.max_range and to_block - from_block + 1 > self.max_range:
            raise RuntimeError("some provider-specific wording")
        self.ranges.append((from_block, to_block))

    def get_deposited_amount(self, token, from_address, to_address, from_block, to_block):
        assert (token, from_address, to_address) == (TOKEN, CLIENT, PAYEE)
        self._check_range(from_block, to_block)
        return sum(amount for block, amount in self.deposits_by_block.items() if from_block <= block <= to_block)

    def get_payer_rail_ids(self, token, payer):
        assert (token, payer) == (TOKEN, PAYEE)
        return self.rail_ids

    def get_one_time_payments(self, rail_ids, from_block, to_block):
        self._check_range(from_block, to_block)
        return sum(amount for block, (rail_id, amount) in self.payments_by_block.items()
                   if from_block <= block <= to_block and rail_id in rail_ids)


class ChainTestCase(unittest.TestCase):
    def chain(self, fake: FakeFileCoinPay, latest_block: int = 5000) -> FakeFileCoinPay:
        for p in (patch.object(repair_funding, "FileCoinPay", lambda: fake),
                  patch.object(repair_funding, "Web3Service", lambda: SimpleNamespace(get_block_number=lambda: latest_block)),
                  patch.object(_repair, "client_address", lambda: CLIENT)):
            p.start()
            self.addCleanup(p.stop)
        return fake

    def confirm(self, answer=True) -> list:
        prompts = []
        p = patch.object(_repair.utils, "confirm", lambda text, **kwargs: prompts.append((text, kwargs)) or answer)
        p.start()
        self.addCleanup(p.stop)
        return prompts


class FundingTests(ChainTestCase):
    def test_scan_shrinks_range_without_gaps_or_overlaps(self):
        fake = self.chain(FakeFileCoinPay({120: 3, 900: 4, 4999: 5}, max_range=300))
        self.assertEqual(repair_funding.get_repair_deposits(TOKEN, CLIENT, PAYEE, 100), 12)
        covered = [block for start, end in fake.ranges for block in range(start, end + 1)]
        self.assertEqual(covered, list(range(100, 5001)))

    def test_scan_raises_when_history_is_unavailable(self):
        self.chain(FakeFileCoinPay({}, fail_before=4000))
        with self.assertRaises(repair_funding.FundingHistoryUnavailable):
            repair_funding.get_repair_deposits(TOKEN, CLIENT, PAYEE, 100)

    def test_spending_counts_only_the_payees_rails_since_the_deal_was_proposed(self):
        self.chain(FakeFileCoinPay({}, payments_by_block={50: (7, 100), 200: (7, 3), 300: (8, 4), 400: (9, 1000)}, rail_ids=[7, 8]))
        self.assertEqual(repair_funding.get_repair_spending(TOKEN, PAYEE, 100), 7)

    def test_spending_without_rails_needs_no_log_scan(self):
        fake = self.chain(FakeFileCoinPay({}, fail_before=4000))
        self.assertEqual(repair_funding.get_repair_spending(TOKEN, PAYEE, 100), 0)
        self.assertEqual(fake.ranges, [])

    def test_available_is_deposits_minus_spending_never_negative(self):
        self.chain(FakeFileCoinPay({200: 10}, payments_by_block={300: (7, 4)}, rail_ids=[7]))
        funding = repair_funding.get_repair_funding(TOKEN, CLIENT, PAYEE, 100)
        self.assertEqual((funding.deposited, funding.spent, funding.available), (10, 4, 6))
        self.assertEqual(repair_funding.RepairFunding(deposited=1, spent=5).available, 0)


class PreviousDepositTests(ChainTestCase):
    def check(self, **kwargs):
        return _repair._check_previous_deposits(TOKEN, PAYEE, 100, COST, DECIMALS, "USDFC", kwargs.get("allow_unverified_history", False),
                                                kwargs.get("allow_repeat_deposit", False), kwargs.get("covered_is_done", False))

    def test_fails_closed_when_history_is_unavailable(self):
        self.chain(FakeFileCoinPay({}, fail_before=4000))
        with self.assertRaisesRegex(click.ClickException, "can't be ruled out"):
            self.check()

    def test_unverified_history_needs_flag_and_confirmation_defaulting_to_no(self):
        self.chain(FakeFileCoinPay({}, fail_before=4000))
        prompts = self.confirm()
        self.assertEqual(self.check(allow_unverified_history=True), COST)
        self.assertIs(prompts[0][1]["default"], False)

    def test_full_partial_and_covering_previous_deposits(self):
        self.chain(FakeFileCoinPay({}))
        self.assertEqual(self.check(), COST)

        self.chain(FakeFileCoinPay({200: 2 * 10 ** 18}))
        self.assertEqual(self.check(), 3 * 10 ** 18)  # only the shortfall

        self.chain(FakeFileCoinPay({200: COST}))
        with self.assertRaisesRegex(click.ClickException, "not depositing again"):
            self.check()
        self.assertEqual(self.check(covered_is_done=True), 0)  # resuming `client repair`: already paid

    def test_repeat_deposit_needs_flag_and_confirmation(self):
        self.chain(FakeFileCoinPay({200: COST}))
        self.confirm()
        self.assertEqual(self.check(allow_repeat_deposit=True), COST)


class MarkerTests(unittest.TestCase):
    def test_marker_round_trip(self):
        marked = _repair.with_repair_marker(MANIFEST, 10)
        self.assertEqual(marked, f"{MANIFEST}#fcss-repair-of=10")
        self.assertEqual(_repair.get_repair_marker(marked), 10)
        self.assertEqual(_repair.get_repair_marker(_repair.with_repair_marker(marked, 12)), 12)  # an earlier marker is replaced

    def test_only_a_well_formed_fragment_is_a_marker(self):
        for location in (MANIFEST, f"{MANIFEST}#section", f"{MANIFEST}#fcss-repair-of=", f"{MANIFEST}#fcss-repair-of=1x",
                         f"{MANIFEST}#fcss-repair-of=01"):
            self.assertIsNone(_repair.get_repair_marker(location))

    def test_marked_url_must_fit_the_market_limit(self):
        with self.assertRaisesRegex(click.ClickException, "shorter URL"):
            _repair.with_repair_marker("https://m.example/" + "a" * 2040, 10)


class PaymentGuardTests(unittest.TestCase):
    def payable(self, state="ACCEPTED", marker=None):
        location = _repair.with_repair_marker(MANIFEST, marker) if marker else MANIFEST
        view = SimpleNamespace(deal=SimpleNamespace(deal_id=11, client_address=CLIENT, state=PoRepMarketDealState[state]),
                               data=SimpleNamespace(manifest_location=location))
        checked = []
        for p in (patch.object(_repair, "client_address", lambda: CLIENT),
                  patch.object(_repair, "Web3Service", lambda: SimpleNamespace(wait_for_pending_transactions=lambda address: None)),
                  patch.object(_repair, "PoRepMarketViewHelper", lambda: SimpleNamespace(get_deal_view=lambda deal_id: view)),
                  patch.object(_repair, "ensure_same_dataset", lambda deal_view, repair_of: checked.append(repair_of)),
                  patch.object(_repair, "repair_payment_token", side_effect=click.ClickException("stop here"))):
            p.start()
            self.addCleanup(p.stop)
        return checked

    def test_deposit_waits_for_the_sp_to_accept_the_deal(self):
        for state, message in (("PROPOSED", "still PROPOSED"), ("REJECTED", "expected ACCEPTED or ACTIVE")):
            with self.subTest(state=state):
                self.payable(state)
                with self.assertRaisesRegex(click.ClickException, message):
                    _repair.pay_repair_retrieval(11)

    def test_deposit_refuses_a_deal_marked_for_another_repair(self):
        self.payable(marker=12)
        with self.assertRaisesRegex(click.ClickException, "marked as the repair of deal ID 12, not 10"):
            _repair.pay_repair_retrieval(11, 10)

    def test_deposit_takes_the_repaired_deal_from_the_marker(self):
        checked = self.payable(marker=10)
        with self.assertRaisesRegex(click.ClickException, "stop here"):
            _repair.pay_repair_retrieval(11)
        self.assertEqual(checked, [10])


class SameDatasetTests(unittest.TestCase):
    def use_datasets(self, repaired, repair):
        views = {10: SimpleNamespace(name="repaired"), 11: SimpleNamespace(name="repair", deal=SimpleNamespace(deal_id=11))}
        datasets = {"repaired": repaired, "repair": repair}
        for p in (patch.object(_repair, "PoRepMarketViewHelper", lambda: SimpleNamespace(get_deal_view=lambda deal_id: views[deal_id])),
                  patch.object(_repair, "deal_dataset", lambda view: datasets[view.name])):
            p.start()
            self.addCleanup(p.stop)
        return views[11]

    def test_same_piece_set_is_the_same_dataset(self):
        _repair.ensure_same_dataset(self.use_datasets(b"pieces", b"pieces"), 10)

    def test_other_piece_set_is_refused(self):
        with self.assertRaisesRegex(click.ClickException, "does not store the same pieces"):
            _repair.ensure_same_dataset(self.use_datasets(b"pieces", b"other"), 10)

    def test_unknown_repaired_dataset_is_refused(self):
        with self.assertRaisesRegex(click.ClickException, "can't be established"):
            _repair.ensure_same_dataset(self.use_datasets(None, b"pieces"), 10)


if __name__ == "__main__":
    unittest.main()
