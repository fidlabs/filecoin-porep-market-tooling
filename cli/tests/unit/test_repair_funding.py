import click
import pytest

from cli.commands import repair_funding
from cli.commands.client import _repair

TOKEN, PAYEE, CLIENT = "0xToken", "0xPayee", "0xClient"
DECIMALS, COST = 18, 5 * 10 ** 18


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


@pytest.fixture
def chain(monkeypatch):
    def setup(fake: FakeFileCoinPay, latest_block: int):
        monkeypatch.setattr(repair_funding, "FileCoinPay", lambda: fake)
        monkeypatch.setattr(repair_funding, "Web3Service", lambda: type("W", (), {"get_block_number": lambda self: latest_block})())
        monkeypatch.setattr(_repair, "client_address", lambda: CLIENT)
        return fake
    return setup


def test_scan_shrinks_range_without_gaps_or_overlaps(chain):
    fake = chain(FakeFileCoinPay({120: 3, 900: 4, 4999: 5}, max_range=300), latest_block=5000)
    assert repair_funding.get_repair_deposits(TOKEN, CLIENT, PAYEE, 100) == 12

    covered = [block for start, end in fake.ranges for block in range(start, end + 1)]
    assert covered == list(range(100, 5001))


def test_scan_raises_when_history_is_unavailable(chain):
    chain(FakeFileCoinPay({}, fail_before=4000), latest_block=5000)
    with pytest.raises(repair_funding.FundingHistoryUnavailable):
        repair_funding.get_repair_deposits(TOKEN, CLIENT, PAYEE, 100)


def test_spending_counts_only_the_payees_rails_since_the_deal_was_proposed(chain):
    chain(FakeFileCoinPay({}, payments_by_block={50: (7, 100), 200: (7, 3), 300: (8, 4), 400: (9, 1000)}, rail_ids=[7, 8]),
          latest_block=5000)
    assert repair_funding.get_repair_spending(TOKEN, PAYEE, 100) == 7


def test_spending_without_rails_needs_no_log_scan(chain):
    fake = chain(FakeFileCoinPay({}, fail_before=4000), latest_block=5000)
    assert repair_funding.get_repair_spending(TOKEN, PAYEE, 100) == 0
    assert not fake.ranges


def test_funding_available_is_deposits_minus_spending(chain):
    chain(FakeFileCoinPay({200: 10}, payments_by_block={300: (7, 4)}, rail_ids=[7]), latest_block=5000)
    funding = repair_funding.get_repair_funding(TOKEN, CLIENT, PAYEE, 100)
    assert (funding.deposited, funding.spent, funding.available) == (10, 4, 6)


def test_funding_available_is_never_negative():
    assert repair_funding.RepairFunding(deposited=1, spent=5).available == 0


def check(**kwargs):
    return _repair._check_previous_deposits(TOKEN, PAYEE, 100, COST, DECIMALS, "USDFC",
                                           kwargs.get("allow_unverified_history", False), kwargs.get("allow_repeat_deposit", False))


def test_fails_closed_when_history_is_unavailable(chain):
    chain(FakeFileCoinPay({}, fail_before=4000), latest_block=5000)
    with pytest.raises(click.ClickException, match="can't be ruled out"):
        check()


def test_unverified_history_needs_flag_and_confirmation(chain, monkeypatch):
    chain(FakeFileCoinPay({}, fail_before=4000), latest_block=5000)
    prompts = []
    monkeypatch.setattr(_repair.utils, "confirm", lambda text, **kwargs: prompts.append((text, kwargs)) or True)
    assert check(allow_unverified_history=True) == COST
    assert prompts and prompts[0][1]["default"] is False


def test_no_previous_deposits_pays_full_cost(chain):
    chain(FakeFileCoinPay({}), latest_block=5000)
    assert check() == COST


def test_previous_deposits_covering_the_cost_refuse_by_default(chain):
    chain(FakeFileCoinPay({200: COST}), latest_block=5000)
    with pytest.raises(click.ClickException, match="not depositing again"):
        check()


def test_repeat_deposit_needs_flag_and_confirmation(chain, monkeypatch):
    chain(FakeFileCoinPay({200: COST}), latest_block=5000)
    monkeypatch.setattr(_repair.utils, "confirm", lambda text, **kwargs: True)
    assert check(allow_repeat_deposit=True) == COST


def test_partial_previous_deposit_pays_only_the_shortfall(chain):
    chain(FakeFileCoinPay({200: 2 * 10 ** 18}), latest_block=5000)
    assert check() == 3 * 10 ** 18


@pytest.mark.parametrize("state, message", [("PROPOSED", "still PROPOSED"), ("REJECTED", "expected ACCEPTED or ACTIVE")])
def test_deposit_waits_for_the_sp_to_accept_the_deal(monkeypatch, state, message):
    from types import SimpleNamespace
    from cli.services.contracts.porep_market import PoRepMarketDealState

    deal = SimpleNamespace(deal=SimpleNamespace(client_address=CLIENT, state=PoRepMarketDealState[state]))
    monkeypatch.setattr(_repair, "client_address", lambda: CLIENT)
    monkeypatch.setattr(_repair, "Web3Service", lambda: SimpleNamespace(wait_for_pending_transactions=lambda address: None))
    monkeypatch.setattr(_repair, "PoRepMarketViewHelper", lambda: SimpleNamespace(get_deal_view=lambda deal_id: deal))

    with pytest.raises(click.ClickException, match=message):
        _repair.pay_repair_retrieval(1)
