import importlib
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import click

from cli.commands.repair_utils import RetrievalQuote

od = importlib.import_module("cli.commands.sp.onboard_data")

# `retrieval-client fetch` flags common to LPR main and v1-maintenance (v1-maintenance has no --pay-token-address)
RETRIEVAL_CLIENT_FETCH_FLAGS = {f"--{flag}" for flag in (
    "cid", "cid-file", "dry-run", "expires-in-sec", "filpay-private-key", "filpay-private-key-env", "filpay-private-key-file",
    "manifest", "no-progress", "out-dir", "parallel", "pay-debug", "pay-payments-address", "pay-rpc-url", "sp-base-url",
    "verbose", "yes")}


def test_lpr_download_claims_allocations_in_process(tmp_path, monkeypatch):
    pieces = [{"pieceCid": "bagaA", "fileSize": 1, "pieceSize": 128, "storagePath": "bagaA.car"},
              {"pieceCid": "bagaB", "fileSize": 1, "pieceSize": 128, "storagePath": "sub/renamed.car"}]

    commands = []

    def fake_run(command, **kwargs):  # retrieval-client stand-in: writes <cid>.car files into --out-dir
        commands.append(command)
        out_dir = tmp_path / "out"
        for cid in Path(command[command.index("--cid-file") + 1]).read_text(encoding="utf-8").split():
            (out_dir / f"{cid}.car").write_text("car")

    claims = []
    monkeypatch.setenv("RPC_URL", "https://rpc.example")
    monkeypatch.setattr(od, "get_retrieval_client_path", lambda: "retrieval-client")
    monkeypatch.setattr(od, "_ensure_payee_key", lambda deal, key_file: None)
    monkeypatch.setattr(od, "_quote_download", lambda pieces, host: RetrievalQuote(total=Decimal(1), paid_pieces=2, free_pieces=0))
    monkeypatch.setattr(od, "_ensure_repair_funded", lambda deal, quote, allow: None)
    monkeypatch.setattr(od, "_echo_download_summary", lambda pieces, no_summary: None)
    monkeypatch.setattr(od, "FileCoinPay", lambda: SimpleNamespace(address=lambda: "0xPay"))
    monkeypatch.setattr(od, "repair_payment_token", lambda deal: "0xToken")
    monkeypatch.setattr(od.utils, "confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(od.subprocess, "run", fake_run)
    monkeypatch.setattr(od.claim_allocations_command, "callback", lambda **kwargs: claims.append(kwargs))

    (tmp_path / "out").mkdir()
    deal = SimpleNamespace(deal=SimpleNamespace(deal_id=7))
    with click.Context(od.onboard_data) as ctx:
        od._download_with_lpr(ctx, deal, pieces, "https://sp.example", (tmp_path / "out").resolve(), True, None, "boost")

    assert (tmp_path / "out" / "sub" / "renamed.car").exists()
    assert [(c["software"], c["deal_id"], c["cid"], c["cars_dir"].endswith(d)) for c, d in zip(claims, ["out", "sub"])] == \
           [("boost", 7, "bagaA", True), ("boost", 7, "bagaB", True)]

    # every flag passed must exist in all retrieval-client builds (LPR main and v1-maintenance)
    passed = {arg for arg in commands[0] if arg.startswith("--")}
    assert passed <= RETRIEVAL_CLIENT_FETCH_FLAGS, passed - RETRIEVAL_CLIENT_FETCH_FLAGS
