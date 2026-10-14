from types import SimpleNamespace

import click
import pytest

from cli.commands import repair_utils

MAINNET_USDFC = "0x80B98d3aa09ffff255c3ba4A241111Ff1262F045"
OTHER_TOKEN = "0x1111111111111111111111111111111111111111"


@pytest.fixture
def chain(monkeypatch):
    def on(chain_id: int):
        monkeypatch.delenv("SP_PROXY_PAY_TOKEN_ADDRESS", raising=False)
        monkeypatch.setattr(repair_utils, "Web3Service", lambda: SimpleNamespace(get_chain_id=lambda: chain_id))
    return on


def test_usdfc_from_the_chain(chain):
    chain(314)
    assert repair_utils.usdfc_token() == MAINNET_USDFC


def test_usdfc_override_for_devnets(chain, monkeypatch):
    chain(31415926)
    monkeypatch.setenv("SP_PROXY_PAY_TOKEN_ADDRESS", OTHER_TOKEN)
    assert repair_utils.usdfc_token().lower() == OTHER_TOKEN


def test_unknown_chain_needs_the_override(chain):
    chain(31415926)
    with pytest.raises(click.ClickException, match="SP_PROXY_PAY_TOKEN_ADDRESS"):
        repair_utils.usdfc_token()


def test_usdfc_deal_is_accepted(chain):
    chain(314)
    deal = SimpleNamespace(deal=SimpleNamespace(deal_id=7), payment=SimpleNamespace(payment_token=MAINNET_USDFC))
    assert repair_utils.repair_payment_token(deal) == MAINNET_USDFC


def test_non_usdfc_deal_is_refused(chain):
    chain(314)
    deal = SimpleNamespace(deal=SimpleNamespace(deal_id=7), payment=SimpleNamespace(payment_token=OTHER_TOKEN))
    with pytest.raises(click.ClickException, match="only USDFC deals can be repaired"):
        repair_utils.repair_payment_token(deal)
