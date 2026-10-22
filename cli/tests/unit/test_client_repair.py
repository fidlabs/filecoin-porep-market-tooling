import importlib
from types import SimpleNamespace

import click
import pytest

from cli.commands.client import _repair
from cli.services.contracts.porep_market import PoRepMarketDealState

repair_module = importlib.import_module("cli.commands.client.repair")

CLIENT, HASH = "0xClient", b"\x01" * 32
OLD = SimpleNamespace(deal=SimpleNamespace(deal_id=10, provider_id="f01", proposed_at_epoch=1000, client_address=CLIENT),
                      data=SimpleNamespace(manifest_hash=HASH, manifest_location="https://m.example/manifest.json"))


MANIFEST = "https://m.example/manifest.json"


def deal(deal_id, state, provider_id="f02", proposed_at_epoch=2000, manifest_hash=HASH, marker: int | None = 10):
    location = MANIFEST if marker is None else f"{MANIFEST}#fcss-repair-of={marker}"
    return SimpleNamespace(deal=SimpleNamespace(deal_id=deal_id, state=PoRepMarketDealState[state], provider_id=provider_id,
                                                proposed_at_epoch=proposed_at_epoch, client_address=CLIENT),
                           data=SimpleNamespace(manifest_hash=manifest_hash, manifest_location=location))


@pytest.fixture
def chain(monkeypatch):
    def setup(*views):
        by_id = {view.deal.deal_id: view for view in views}
        monkeypatch.setattr(repair_module, "client_address", lambda: CLIENT)
        monkeypatch.setattr(repair_module.commands_utils, "get_client_deals", lambda client: [view.deal for view in views])
        monkeypatch.setattr(repair_module, "PoRepMarketViewHelper", lambda: SimpleNamespace(get_deal_view=lambda deal_id: by_id[deal_id]))
        return by_id
    return setup


@pytest.fixture
def prompts(monkeypatch):
    asked = []

    def fake_confirm(text, default=False, abort=False, **kwargs):
        asked.append((text, default))
        if abort:
            raise click.Abort()
        return False

    monkeypatch.setattr(repair_module.utils, "confirm", fake_confirm)
    return asked


def test_marker_round_trip():
    url = _repair.with_repair_marker(MANIFEST, 10)
    assert url == f"{MANIFEST}#fcss-repair-of=10"
    assert _repair.get_repair_marker(url) == 10
    # repairing a repair deal: its marker is replaced, not stacked
    assert _repair.get_repair_marker(_repair.with_repair_marker(url, 12)) == 12


@pytest.mark.parametrize("location", [MANIFEST, f"{MANIFEST}#section", f"{MANIFEST}#fcss-repair-of=", f"{MANIFEST}#fcss-repair-of=1x",
                                      f"{MANIFEST}#fcss-repair-of=10&x=1", f"{MANIFEST}?fcss-repair-of=10"])
def test_only_a_well_formed_fragment_is_a_marker(location):
    assert _repair.get_repair_marker(location) is None


def test_marked_url_must_fit_the_market_limit():
    with pytest.raises(click.ClickException, match="2048"):
        _repair.with_repair_marker("https://m.example/" + "x" * 2020, 10)


def test_resumes_the_latest_pending_deal_marked_for_this_repair(chain):
    chain(deal(11, "PROPOSED"), deal(12, "ACCEPTED"), deal(13, "REJECTED"))
    assert repair_module._find_repair_deal(OLD).deal.deal_id == 12


def test_marked_active_deal_means_the_repair_is_done(chain):
    chain(deal(11, "ACTIVE"), deal(12, "PROPOSED"))
    assert repair_module._find_repair_deal(OLD).deal.deal_id == 11


@pytest.mark.parametrize("other", [
    deal(11, "ACTIVE", marker=None),                   # the dataset's surviving original copy, proposed after DEAL_ID
    deal(11, "ACCEPTED", marker=12),                   # the repair of another deal of this dataset
    deal(11, "ACCEPTED", provider_id="f01"),           # the repaired deal's own SP
    deal(11, "ACCEPTED", manifest_hash=b"\x02" * 32),  # another dataset
    deal(11, "REJECTED"),
])
def test_ignores_deals_that_are_not_this_repair(chain, prompts, other):
    chain(other)
    assert repair_module._find_repair_deal(OLD) is None
    assert not prompts


def test_pending_unmarked_original_copy_is_never_picked(chain, prompts):
    # the dataset's other original copy, still being onboarded: same client, same dataset, newer, pending
    chain(deal(11, "ACCEPTED", marker=None))
    with pytest.raises(click.Abort):
        repair_module._find_repair_deal(OLD)
    (text, default), = prompts
    assert "--repair-deal" in text and default is False


def test_old_terms_convert_back_exactly(monkeypatch):
    monkeypatch.setattr(repair_module, "ERC20Contract", lambda address: SimpleNamespace(decimals=lambda: 18))
    monkeypatch.setattr(repair_module, "PoRepMarket", lambda: SimpleNamespace(get_sector_size_bytes=lambda: 32 * 2 ** 30))
    old = SimpleNamespace(deal=SimpleNamespace(deal_id=2), payment=SimpleNamespace(payment_token="0xUSDFC", price_per_32_gib_per_month=125 * 10 ** 15),
                          terms=SimpleNamespace(duration_epochs=518400))
    assert repair_module._old_price_per_tib(old) == 4.0
    assert repair_module._old_duration_months(old) == 6

    old.terms.duration_epochs += 1
    with pytest.raises(click.UsageError, match="--duration-months"):
        repair_module._old_duration_months(old)


@pytest.fixture
def flow(monkeypatch, chain):
    def setup(new_state_after_wait: str):
        new = deal(11, "PROPOSED")
        chain(OLD, new)
        steps = []
        monkeypatch.setattr(repair_module.SelfUpdateService, "check_and_prompt", lambda manual: None)
        monkeypatch.setattr(repair_module._repair, "ensure_repairable", lambda view: None)
        monkeypatch.setattr(repair_module, "ensure_usdfc", lambda token, subject: None)
        monkeypatch.setattr(repair_module, "_find_repair_deal", lambda old: new)
        monkeypatch.setattr(repair_module, "_wait_for_acceptance", lambda deal_id, minutes: deal(deal_id, new_state_after_wait))
        monkeypatch.setattr(repair_module._repair, "pay_repair_retrieval", lambda *args, **kwargs: steps.append(("pay", args[0], kwargs["covered_is_done"])))
        monkeypatch.setattr(repair_module.init_deal, "callback", lambda deal_id: steps.append(("init", deal_id)))
        monkeypatch.setattr(repair_module.make_allocations, "callback", lambda deal_id, **kwargs: steps.append(("allocate", deal_id)))
        OLD.payment = SimpleNamespace(payment_token="0xUSDFC")
        return steps
    return setup


def run_repair(**kwargs):
    with click.Context(repair_module.repair) as ctx:
        ctx.invoke(repair_module.repair, deal_id=10, **kwargs)


def test_accepted_repair_deal_is_funded_initialized_and_allocated(flow):
    steps = flow("ACCEPTED")
    run_repair()
    assert steps == [("pay", 11, True), ("init", 11), ("allocate", 11)]


def test_unaccepted_repair_deal_stops_without_paying(flow, capsys):
    steps = flow("PROPOSED")
    run_repair()
    assert steps == []
    assert "client repair 10" in capsys.readouterr().out


def test_rejected_repair_deal_asks_to_rerun(flow):
    steps = flow("REJECTED")
    with pytest.raises(click.ClickException, match="propose a new one"):
        run_repair()
    assert steps == []


def test_resumed_deposit_already_covered_is_not_an_error(monkeypatch):
    monkeypatch.setattr(_repair, "client_address", lambda: CLIENT)
    monkeypatch.setattr(_repair, "get_repair_deposits", lambda token, client, payee, since: 5)
    assert _repair._check_previous_deposits("0xT", "0xP", 1, 5, 0, "USDFC", False, False, covered_is_done=True) == 0
    with pytest.raises(click.ClickException, match="not depositing again"):
        _repair._check_previous_deposits("0xT", "0xP", 1, 5, 0, "USDFC", False, False)


def test_done_repair_is_reported_without_paying_again(flow, monkeypatch, capsys):
    steps = flow("ACCEPTED")
    monkeypatch.setattr(repair_module, "_find_repair_deal", lambda old: deal(11, "ACTIVE"))
    run_repair()
    assert steps == []
    assert "repair deal ID 11" in capsys.readouterr().out


def test_new_repair_deal_is_proposed_with_the_marker(monkeypatch):
    proposed = []
    monkeypatch.setattr(repair_module.commands_utils, "fetch_manifest", lambda url, **kwargs: ([{"pieces": []}], b""))
    monkeypatch.setattr(repair_module, "find_healthy_source",
                        lambda *args: SimpleNamespace(base_url="https://healthy.example", quote=SimpleNamespace(total=0, paid_pieces=0)))
    monkeypatch.setattr(repair_module, "client_signer", lambda: None)
    monkeypatch.setattr(repair_module.commands_utils, "propose_deal", lambda signer, url, *args: proposed.append(url) or 11)
    old = SimpleNamespace(deal=SimpleNamespace(deal_id=10, provider_id="f01", deal_type="PUBLIC"),
                          data=SimpleNamespace(manifest_hash=HASH, manifest_location=MANIFEST),
                          required_slis=SimpleNamespace(retrievability_bps=9000, bandwidth_bytes_per_second=125_000, latency_ms=0, indexing_pct=0),
                          payment=SimpleNamespace(payment_token="0xUSDFC"))
    assert repair_module._propose_repair_deal(old, None, 4.0, 6)[0] == 11
    assert proposed == [f"{MANIFEST}#fcss-repair-of=10"]


def _payable(monkeypatch, marker):
    view = deal(11, "ACCEPTED", marker=marker)
    monkeypatch.setattr(_repair, "client_address", lambda: CLIENT)
    monkeypatch.setattr(_repair, "Web3Service", lambda: SimpleNamespace(wait_for_pending_transactions=lambda address: None))
    monkeypatch.setattr(_repair, "PoRepMarketViewHelper", lambda: SimpleNamespace(get_deal_view=lambda deal_id: view))
    checked = []
    monkeypatch.setattr(_repair, "ensure_same_dataset", lambda deal_view, repair_of: checked.append(repair_of))
    monkeypatch.setattr(_repair, "repair_payment_token", lambda deal_view: (_ for _ in ()).throw(click.ClickException("stop here")))
    return checked


def test_deposit_refuses_a_deal_marked_for_another_repair(monkeypatch):
    _payable(monkeypatch, marker=12)
    with pytest.raises(click.ClickException, match="marked as the repair of deal ID 12, not 10"):
        _repair.pay_repair_retrieval(11, 10)


def test_deposit_takes_the_repaired_deal_from_the_marker(monkeypatch):
    checked = _payable(monkeypatch, marker=10)
    with pytest.raises(click.ClickException, match="stop here"):
        _repair.pay_repair_retrieval(11)
    assert checked == [10]


@pytest.fixture
def given(chain, monkeypatch):
    monkeypatch.setattr(repair_module, "resolve_repair_payee", lambda view: "0xPayee")
    return lambda view: chain(view) and repair_module._given_repair_deal(OLD, view.deal.deal_id)


def test_given_unmarked_deal_needs_a_confirmation_defaulting_to_no(given, prompts):
    with pytest.raises(click.Abort):
        given(deal(11, "ACCEPTED", marker=None))
    (text, default), = prompts
    assert "no repair marker" in text and "0xPayee" in text and default is False


def test_given_unmarked_deal_continues_once_confirmed(given, monkeypatch):
    monkeypatch.setattr(repair_module.utils, "confirm", lambda text, **kwargs: True)
    assert given(deal(11, "PROPOSED", marker=None)).deal.deal_id == 11


def test_given_deal_marked_for_this_repair_needs_no_confirmation(given, prompts):
    assert given(deal(11, "ACCEPTED")).deal.deal_id == 11
    assert not prompts


@pytest.mark.parametrize("view, message", [
    (deal(11, "ACCEPTED", marker=12), "marked as the repair of deal ID 12"),
    (deal(11, "ACCEPTED", provider_id="f01", marker=None), "own provider"),
    (deal(11, "ACCEPTED", manifest_hash=b"\x02" * 32, marker=None), "another dataset"),
    (deal(11, "REJECTED", marker=None), "state REJECTED"),
])
def test_given_deal_that_cannot_be_this_repair_is_refused(given, prompts, view, message):
    with pytest.raises(click.ClickException, match=message):
        given(view)
    assert not prompts
