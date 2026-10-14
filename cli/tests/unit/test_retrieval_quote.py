import stat
import subprocess
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from cli.commands import repair_utils
from test_onboard_lpr import RETRIEVAL_CLIENT_FETCH_FLAGS  # pylint: disable=import-error

# summary lines as printed by LPR's printFetchQuote (main and v1-maintenance)
PAID = """
Quote:
  CID           TYPE  SIZE      PRICE       SOURCE
  baga...wmq    paid  30.5 GiB  0.31 USDFC  http://127.0.0.1:8787

Total: 1.26 USDFC for 4 paid piece(s).
Chain: this may take some time - several transactions to prepare then one charge per payee.
"""
MIXED = "Total: 0.62 USDFC for 2 paid piece(s); 3 free.\n"
FREE = "All 5 piece(s) are free; no Filecoin Pay charge required.\n"


@pytest.mark.parametrize("output, pieces, expected", [
    (PAID, 4, (Decimal("1.26"), 4, 0)),
    (MIXED, 5, (Decimal("0.62"), 2, 3)),
    (FREE, 5, (Decimal(0), 0, 5)),
])
def test_parse_dry_run_quote(output, pieces, expected):
    quote = repair_utils.parse_dry_run_quote(output, pieces)
    assert (quote.total, quote.paid_pieces, quote.free_pieces) == expected


@pytest.mark.parametrize("output, pieces", [(PAID, 5), (FREE, 4), ("Quote:\n", 1), ("Total: abc USDFC for 1 paid piece(s).\n", 1)])
def test_unexpected_quotes_are_refused(output, pieces):
    with pytest.raises(ValueError):
        repair_utils.parse_dry_run_quote(output, pieces)


@pytest.fixture
def fake_client(monkeypatch):
    calls = []

    def install(returncode=0, stdout=PAID, raise_timeout=False):
        def run(command, **kwargs):
            key = Path(command[command.index("--filpay-private-key-file") + 1])
            calls.append({"command": command, "env": kwargs["env"], "key_mode": stat.S_IMODE(key.stat().st_mode), "key": key})
            if raise_timeout:
                raise subprocess.TimeoutExpired(command, 1)
            return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="dataset incomplete: no usable source for CID baga")

        monkeypatch.setattr(repair_utils, "get_retrieval_client_path", lambda: "retrieval-client")
        monkeypatch.setattr(repair_utils.subprocess, "run", run)
        return calls

    return install


def test_quote_uses_a_throwaway_key_and_common_flags(fake_client, monkeypatch):
    monkeypatch.setenv("CLIENT_PRIVATE_KEY", "placeholder-secret")
    calls = fake_client()

    quote = repair_utils.quote_retrieval("https://sp.example:8787", ["a", "b", "c", "d"])

    assert quote.total == Decimal("1.26")
    call = calls[0]
    assert {arg for arg in call["command"] if arg.startswith("--")} <= RETRIEVAL_CLIENT_FETCH_FLAGS
    assert "--dry-run" in call["command"]
    assert call["key_mode"] == 0o600 and not call["key"].exists()  # owner-only, removed afterwards
    assert "CLIENT_PRIVATE_KEY" not in call["env"]


def test_failed_quote_means_source_unavailable(fake_client):
    fake_client(returncode=1, stdout="")
    with pytest.raises(repair_utils.SourceUnavailable, match="no usable source"):
        repair_utils.quote_retrieval("https://sp.example", ["a"])


def test_timed_out_quote_means_source_unavailable(fake_client):
    fake_client(raise_timeout=True)
    with pytest.raises(repair_utils.SourceUnavailable, match="timed out"):
        repair_utils.quote_retrieval("https://sp.example", ["a"])


def test_wrong_piece_count_means_source_unavailable(fake_client):
    fake_client(stdout=PAID)
    with pytest.raises(repair_utils.SourceUnavailable, match="unexpected retrieval-client output"):
        repair_utils.quote_retrieval("https://sp.example", ["a"])


def test_private_source_addresses_are_refused_before_quoting(monkeypatch):
    monkeypatch.delenv("ALLOW_PRIVATE_MANIFEST_URLS", raising=False)
    monkeypatch.setattr(repair_utils, "quote_retrieval", lambda *a: pytest.fail("must not quote a private address"))
    source, reason = repair_utils.quote_source("http://127.0.0.1:8787", [{"pieceCid": "a"}])
    assert source is None and "disallowed" in reason
