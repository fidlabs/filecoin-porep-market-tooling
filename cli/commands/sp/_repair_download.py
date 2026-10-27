import contextlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import click

from cli import utils
from cli.commands.repair_funding import FundingHistoryUnavailable, base_units_str, get_repair_funding, tokens_to_base_units
from cli.commands.repair_utils import (
    RetrievalQuote,
    SourceUnavailable,
    child_env,
    ensure_secret_file,
    get_retrieval_client_path,
    quote_retrieval,
    repair_payment_token,
    resolve_repair_payee,
    throwaway_key_file,
)
from cli.services.contracts.erc20_contract import ERC20Contract
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.porep_market_view_helper import PoRepMarketDealView
from cli.services.web3_service import EthAddress

# `sp onboard-data --downloader lpr`: download a repair deal's data from another SP's large-paid-retrievals sp-proxy with
# retrieval-client, paying from the deal payee's FileCoinPay account, which the client funds with `client pay-repair-retrieval`.
# A paid download only starts once the client's deposits not yet spent by the payee cover the quote; a free one needs no
# payee key.


def download_with_lpr(ctx,
                      deal: PoRepMarketDealView,
                      pieces: list[dict],
                      download_host: str,
                      output_dir: Path,
                      no_summary: bool,
                      payee_key_file: str | None,
                      allow_unfunded_retrieval: bool = False):
    #
    for piece in pieces:
        _output_file(piece, output_dir)  # refuse a manifest storagePath outside the output directory before paying anything

    retrieval_client_path = get_retrieval_client_path()
    quote = _quote_download(pieces, download_host)

    with contextlib.ExitStack() as stack:
        if quote.paid_pieces:
            _ensure_payee_key(deal, payee_key_file)
            _ensure_repair_funded(deal, quote, allow_unfunded_retrieval)
            key_file = payee_key_file
        else:
            # nothing to pay, so the payee key isn't needed
            click.echo(f"All {quote.free_pieces} piece(s) are free; downloading without the payee key.")
            key_file = str(stack.enter_context(throwaway_key_file()))

        _run_retrieval_client(ctx, retrieval_client_path, pieces, download_host, output_dir, no_summary, key_file)

    _move_downloads(pieces, output_dir)


# exact quote of what is left to download, taken right before downloading it
def _quote_download(pieces: list[dict], download_host: str) -> RetrievalQuote:
    click.echo(f"\nQuoting {len(pieces)} piece(s) from {download_host}...")

    try:
        return quote_retrieval(download_host, [piece["pieceCid"] for piece in pieces])
    except SourceUnavailable as e:
        raise click.ClickException(f"Source {download_host} cannot serve the data: {e}") from e


# retrieval-client pays from the deal payee's FileCoinPay account: fail before spending anything if the key isn't that payee's
def _ensure_payee_key(deal: PoRepMarketDealView, payee_key_file: str | None):
    if payee_key_file:
        # the payee also receives the SP's deal revenue, so treat its key like an SSH private key
        ensure_secret_file(Path(payee_key_file), "payee key file")
        private_key = Path(payee_key_file).read_text(encoding="utf-8").strip()
    elif os.getenv("FILPAY_PRIVATE_KEY"):
        click.echo("WARNING: FILPAY_PRIVATE_KEY exposes the payee key, which also receives your deal revenue, to every process "
                   "started from this environment; prefer --payee-key-file with a chmod 600 file.")
        private_key = os.environ["FILPAY_PRIVATE_KEY"].strip()
    else:
        raise click.UsageError("A paid repair download requires the deal payee private key: set --payee-key-file / SP_PAYEE_KEY_FILE "
                               "or FILPAY_PRIVATE_KEY")

    try:
        key_address = EthAddress.from_private_key(private_key if private_key.startswith("0x") else f"0x{private_key}")
    except ValueError as e:
        raise click.ClickException("Invalid payee private key") from e

    payee = resolve_repair_payee(deal)

    if key_address != payee:
        raise click.ClickException(f"Payee key address {key_address} does not match deal ID {deal.deal.deal_id} payee {payee}; "
                                   f"the repair retrieval is funded in the deal payee's FileCoinPay account.")


# The client's deposit is the go-signal and the spending cap for a paid repair download: only start once the client's
# deposits not yet spent by the payee cover the quote.
def _ensure_repair_funded(deal: PoRepMarketDealView, quote: RetrievalQuote, allow_unfunded_retrieval: bool):
    token = ERC20Contract(repair_payment_token(deal))
    token_decimals = token.decimals()
    token_symbol = token.symbol()

    def amount_str(amount: int) -> str:
        return f"{base_units_str(amount, token_decimals)} {token_symbol}"

    needed = tokens_to_base_units(quote.total, token_decimals)
    payee = resolve_repair_payee(deal)
    pay_command = f"`{sys.argv[0]} client pay-repair-retrieval {deal.deal.deal_id}`"

    try:
        funding = get_repair_funding(token.address(), deal.deal.client_address, payee, deal.deal.proposed_at_epoch)

    except FundingHistoryUnavailable as e:
        if not allow_unfunded_retrieval:
            raise click.ClickException(f"Could not check the client's repair funding of {payee}: {e}\n"
                                       f"Use an RPC_URL that serves logs back to epoch {deal.deal.proposed_at_epoch}, or re-run with "
                                       f"--allow-unfunded-retrieval to download anyway; whatever the deposits don't cover is paid "
                                       f"from the payee's own funds.") from e

        click.echo(f"WARNING: client funding could not be checked ({e}); downloading anyway (--allow-unfunded-retrieval).")
        return

    click.echo(f"Repair retrieval quote: {amount_str(needed)} for {quote.paid_pieces} paid piece(s)\n"
               f"  Client deposits to {payee} since the deal was proposed: {amount_str(funding.deposited)}\n"
               f"  Spent by {payee} on retrievals since then: {amount_str(funding.spent)}\n"
               f"  Available: {amount_str(funding.available)}")

    if funding.available >= needed:
        return

    shortfall = needed - funding.available

    if allow_unfunded_retrieval:
        click.echo(f"WARNING: client funding is short by {amount_str(shortfall)}; downloading anyway (--allow-unfunded-retrieval), "
                   f"so the rest is paid from the payee's own funds.")
        return

    raise click.ClickException(f"Waiting for client funding: quote {amount_str(needed)}, available {amount_str(funding.available)}, "
                               f"short {amount_str(shortfall)}. The client funds it with {pay_command}; re-run this command "
                               f"afterwards, or use --allow-unfunded-retrieval to pay the difference from the payee's own funds.")


def _run_retrieval_client(ctx,
                          retrieval_client_path: str,
                          pieces: list[dict],
                          download_host: str,
                          output_dir: Path,
                          no_summary: bool,
                          key_file: str | None):
    #
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
        cid_file = Path(f.name)
        f.write("".join(f"{piece['pieceCid']}\n" for piece in pieces))

    if not no_summary:
        for piece in pieces:
            click.echo(f"  {download_host}/piece/{piece['pieceCid']} (large-paid-retrievals) -> {_output_file(piece, output_dir)}")

    try:
        # pay through the same chain and FileCoinPay contract the client funded with `client pay-repair-retrieval`. The token
        # is USDFC (checked by _ensure_repair_funded): retrieval-client resolves it itself, from SP_PROXY_PAY_TOKEN_ADDRESS or
        # the chain default. Only pass flags every retrieval-client build has: --pay-token-address is missing from LPR's
        # v1-maintenance branch.
        defaults = {
            "--pay-rpc-url": utils.get_env_required("RPC_URL"),
            "--pay-payments-address": str(FileCoinPay().address()),
        }

        command = [retrieval_client_path, "fetch",
                   "--sp-base-url", download_host,
                   "--cid-file", str(cid_file),
                   "--out-dir", str(output_dir)]

        for option, value in defaults.items():
            if not any(arg == option or arg.startswith(f"{option}=") for arg in ctx.args):
                command += [option, value]

        # without a key file, retrieval-client reads the payee key from the FILPAY_PRIVATE_KEY env var
        if key_file:
            command += ["--filpay-private-key-file", str(Path(key_file).resolve())]

        command += ctx.args

        utils.confirm(f"\nRunning command:\n  {' '.join(command)}\nContinue?", default=True, abort=True)
        click.echo("\n")
        # the payee key is the only secret retrieval-client gets, and only when it comes from the environment
        subprocess.run(command, check=True, env=child_env(keep=() if key_file else ("FILPAY_PRIVATE_KEY",)))

    except subprocess.CalledProcessError as e:
        raise click.ClickException(f"retrieval-client failed with exit code {e.returncode}; see its output above") from e

    finally:
        cid_file.unlink(missing_ok=True)


def _output_file(piece: dict, output_dir: Path) -> Path:
    output_file = (output_dir / piece["storagePath"]).resolve()

    # disallow path traversal outside of the output directory
    if output_dir not in output_file.parents:
        raise click.ClickException(f"Invalid manifest piece storagePath: {piece['storagePath']}")

    return output_file


# retrieval-client always writes <pieceCid>.car into --out-dir; move each piece to its manifest storagePath, like aria2 names it
def _move_downloads(pieces: list[dict], output_dir: Path):
    for piece in pieces:
        downloaded_file = output_dir / f"{piece['pieceCid']}.car"
        output_file = _output_file(piece, output_dir)

        if not downloaded_file.exists():
            raise click.ClickException(f"retrieval-client did not produce {downloaded_file}")

        if downloaded_file.resolve() != output_file:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            downloaded_file.replace(output_file)
