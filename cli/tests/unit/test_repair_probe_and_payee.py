from decimal import Decimal

import pytest

from cli.commands import repair_funding, repair_utils

GIB = 2 ** 30


@pytest.mark.parametrize("amount, decimals, expected", [
    (Decimal("1.26"), 18, 1_260_000_000_000_000_000),
    (Decimal("0.0000001"), 6, 1),  # finer than the token's decimals: rounded up, never down
    (Decimal(0), 18, 0),
])
def test_quote_to_base_units_rounds_up(amount, decimals, expected):
    assert repair_funding.tokens_to_base_units(amount, decimals) == expected


class _Response:
    def __init__(self, status_code, headers):
        self.status_code, self.headers = status_code, headers

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.mark.parametrize("status, headers, expected", [
    (200, {}, ("free", 31 * GIB)),
    (206, {"Content-Range": f"bytes 0-0/{31 * GIB}"}, ("free", 31 * GIB)),
    (402, {"WWW-Authenticate": "Payment ..."}, ("paid", 31 * GIB)),
    (403, {}, ("private", None)),
    (500, {}, ("unavailable", None)),
])
def test_probe_piece_status(monkeypatch, status, headers, expected):
    monkeypatch.setattr(repair_utils.commands_utils, "validate_and_parse_url", lambda url: None)
    monkeypatch.setattr(repair_utils.requests, "head", lambda *a, **k: _Response(200, {"Content-Length": str(31 * GIB)}))
    monkeypatch.setattr(repair_utils.requests, "get", lambda *a, **k: _Response(status, headers))
    probe = repair_utils.probe_piece("https://sp.example", "baga")
    assert (probe.status, probe.size_bytes) == expected


def test_unreachable_piece_server_is_unavailable(monkeypatch):
    def refuse(*args, **kwargs):
        raise repair_utils.requests.ConnectionError("connection refused")

    monkeypatch.setattr(repair_utils.commands_utils, "validate_and_parse_url", lambda url: None)
    monkeypatch.setattr(repair_utils.requests, "head", refuse)
    assert repair_utils.probe_piece("https://sp.example", "baga").status == "unavailable"


def _deal_with_payee(payee: str):
    from types import SimpleNamespace
    return SimpleNamespace(deal=SimpleNamespace(deal_id=9, provider_id=1234),
                           payment=SimpleNamespace(payee=payee, payment_token="0x80B98d3aa09ffff255c3ba4A241111Ff1262F045"))


@pytest.mark.parametrize("deal_payee, registry_payee, expected", [
    ("0x1c6a2fd1dc31692929D26A227e684bF93D4F8Ecc", None, "0x1c6a2fd1dc31692929D26A227e684bF93D4F8Ecc"),
    ("0x" + "0" * 40, "0xBEC51cd6718237fa96fbE586343956Ba465f30F8", "0xBEC51cd6718237fa96fbE586343956Ba465f30F8"),
])
def test_client_and_sp_resolve_the_same_payee(monkeypatch, deal_payee, registry_payee, expected):
    from types import SimpleNamespace
    monkeypatch.setattr(repair_utils, "SPRegistry", lambda: SimpleNamespace(get_provider_view=lambda pid: SimpleNamespace(payee_address=registry_payee)))
    monkeypatch.setattr(repair_utils, "Web3Service", lambda: SimpleNamespace(w3=lambda: SimpleNamespace(eth=SimpleNamespace(get_code=lambda a: b""))))
    assert repair_utils.resolve_repair_payee(_deal_with_payee(deal_payee)).lower() == expected.lower()


def test_contract_payee_is_refused(monkeypatch):
    from types import SimpleNamespace
    import click
    monkeypatch.setattr(repair_utils, "Web3Service", lambda: SimpleNamespace(w3=lambda: SimpleNamespace(eth=SimpleNamespace(get_code=lambda a: b"\x60\x80"))))
    with pytest.raises(click.ClickException, match="is a contract"):
        repair_utils.resolve_repair_payee(_deal_with_payee("0x1c6a2fd1dc31692929D26A227e684bF93D4F8Ecc"))


@pytest.mark.parametrize("amount, decimals, expected", [
    (1260000000000000000, 18, "1.26"), (0, 18, "0"), (10 ** 18, 18, "1"), (1, 18, "0.000000000000000001"), (123450, 6, "0.12345"),
])
def test_base_units_str_is_exact(amount, decimals, expected):
    assert repair_funding.base_units_str(amount, decimals) == expected
