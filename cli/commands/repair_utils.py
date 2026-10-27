import contextlib
import logging
import os
import re
import secrets
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path

import click
import requests
from hexbytes import HexBytes

from cli import utils
from cli.commands import utils as commands_utils
from cli.services.contracts.evidence_adapter import EvidenceType
from cli.services.contracts.porep_market import PoRepMarketDealState, PoRepMarketDealType
from cli.services.contracts.porep_market_view_helper import PoRepMarketDealView, PoRepMarketViewHelper
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.curio_market_client import CurioMarketDiscovery
from cli.services.piece_set_commitment import PieceSet
from cli.services.web3_service import ActorId, EthAddress, Web3Service

# Shared code for repairs (re-onboarding a dataset with a new SP from an SP that still serves it), used by the client
# commands and `sp onboard-data`:
# - finding a "healthy" SP still serving a dataset, and the large-paid-retrievals (LPR) price it charges,
# - resolving the payee and token the repair retrieval is paid with (the same for client and SP).
#
# Healthy = another provider's ACTIVE, PUBLIC deal (LPR only lets deal owners retrieve private deals) for the same dataset,
# whose advertised HTTP piece endpoint actually serves every piece: checked, and priced, with `retrieval-client fetch
# --dry-run` (LPR's own quotes; free pieces cost nothing).
#
# Same dataset = same piece set. A sector placement deal's on-chain manifest hash is its piece-set commitment; a DataCap
# deal's is the keccak of its raw manifest, so its manifest is fetched, checked against that hash, and its piece set computed.

logger = logging.getLogger(__name__)

CID_CONTACT_URL = "https://cid.contact"
CID_CONTACT_TIMEOUT_SECONDS = 30

# text multiaddrs as cid.contact returns them: /<host proto>/<host>/tcp/<port>/<transport>; Curio advertises its market HTTP
# server as libp2p (w)ss on the same host:port
_HTTP_MULTIADDR = re.compile(r"^/(?:ip4|ip6|dns|dns4|dns6)/([^/]+)/tcp/(\d+)/(http|https|tls/http|wss|ws)(?:/|$)")

_SECRET_ENV_VAR = re.compile(r"(PRIVATE_KEY|LOTUS_TOKEN|DATABASE_URL)$")


# Environment for external programs: everything except this CLI's secrets (private keys, Lotus tokens, database URLs),
# which they don't need; `keep` names the exceptions.
def child_env(keep: tuple[str, ...] = (), **extra: str) -> dict[str, str]:
    env = {name: value for name, value in os.environ.items() if name in keep or not _SECRET_ENV_VAR.search(name)}
    env.update(extra)
    return env


# Like SSH does for private key files: a file holding a secret must be owned by the current user and not be accessible
# by group or others. No-op where POSIX permissions don't apply (Windows).
def secret_file_problem(path: Path) -> str | None:
    if os.name != "posix":
        return None

    stat = path.stat()

    if stat.st_uid != os.getuid():
        return f"{path} is owned by another user (uid {stat.st_uid})"

    if stat.st_mode & 0o077:
        return f"{path} is accessible by other users (mode {oct(stat.st_mode & 0o777)}); run: chmod 600 {path}"

    return None


def ensure_secret_file(path: Path, description: str):
    problem = secret_file_problem(path)

    if problem:
        raise click.ClickException(f"Refusing to use {description}: {problem}")


def get_retrieval_client_path() -> str:
    retrieval_client_path = utils.get_env_required("RETRIEVAL_CLIENT_PATH", default="retrieval-client")

    if retrieval_client_path != "retrieval-client":
        retrieval_client_path = Path(retrieval_client_path).resolve()

    # noinspection PyBroadException
    try:
        subprocess.run([retrieval_client_path, "fetch", "--help"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    # pylint: disable=broad-exception-caught
    except Exception as e:
        click.echo("retrieval-client not found. Please install large-paid-retrievals retrieval-client: repairs use it for quotes and paid downloads.\n"
                   "See https://github.com/fidlabs/large-paid-retrievals#for-dataset-consumers for installation instructions:\n"
                   "  git clone https://github.com/fidlabs/large-paid-retrievals && cd large-paid-retrievals && "
                   "go build -o bin/retrieval-client ./cmd/retrieval-client\n"
                   "Set the RETRIEVAL_CLIENT_PATH environment variable if retrieval-client is installed but not in PATH.\n")

        raise click.ClickException(f"{retrieval_client_path} not found:\n{e}") from e

    return str(retrieval_client_path)


class SourceUnavailable(Exception):
    pass


@utils.json_dataclass()
class RetrievalQuote:
    total: Decimal  # USDFC for all paid pieces, as quoted by the source's sp-proxy
    paid_pieces: int
    free_pieces: int


# `retrieval-client fetch --dry-run` summary (LPR fetch_quote.go, identical in main and v1-maintenance); the per-piece table
# truncates CIDs, so only the totals are read, and the piece count must match what was asked for
_QUOTE_TOTAL = re.compile(r"^Total: ([0-9.]+) USDFC for (\d+) paid piece\(s\)(?:; (\d+) free)?\.\s*$", re.MULTILINE)
_QUOTE_ALL_FREE = re.compile(r"^All (\d+) piece\(s\) are free;", re.MULTILINE)
RETRIEVAL_CLIENT_QUOTE_TIMEOUT_SECONDS = 3600


def parse_dry_run_quote(output: str, expected_pieces: int) -> RetrievalQuote:
    total_match = _QUOTE_TOTAL.search(output)
    free_match = _QUOTE_ALL_FREE.search(output)

    if total_match:
        # noinspection PyArgumentList
        quote = RetrievalQuote(total=Decimal(total_match.group(1)), paid_pieces=int(total_match.group(2)),
                               free_pieces=int(total_match.group(3) or 0))
    elif free_match:
        # noinspection PyArgumentList
        quote = RetrievalQuote(total=Decimal(0), paid_pieces=0, free_pieces=int(free_match.group(1)))
    else:
        raise ValueError("no quote summary in retrieval-client output")

    if quote.paid_pieces + quote.free_pieces != expected_pieces:
        raise ValueError(f"quote covers {quote.paid_pieces + quote.free_pieces} piece(s), expected {expected_pieces}")

    return quote


# retrieval-client always loads a key, even when nothing is paid (dry runs, free sources): give it one that holds nothing
@contextlib.contextmanager
def throwaway_key_file():
    with tempfile.TemporaryDirectory() as tmp:
        key_file = Path(tmp) / "throwaway.key"
        key_file.write_text(secrets.token_hex(32), encoding="utf-8")
        key_file.chmod(0o600)
        yield key_file


# Exact quote for every piece from the source, via `retrieval-client fetch --dry-run` (no transactions, no downloads)
def quote_retrieval(base_url: str, piece_cids: list[str]) -> RetrievalQuote:
    retrieval_client_path = get_retrieval_client_path()

    with tempfile.TemporaryDirectory() as tmp, throwaway_key_file() as key_file:
        cid_file = Path(tmp) / "cids.txt"
        cid_file.write_text("\n".join(piece_cids) + "\n", encoding="utf-8")

        command = [retrieval_client_path, "fetch", "--dry-run", "--no-progress",
                   "--sp-base-url", base_url,
                   "--cid-file", str(cid_file),
                   "--out-dir", tmp,
                   "--filpay-private-key-file", str(key_file)]

        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=RETRIEVAL_CLIENT_QUOTE_TIMEOUT_SECONDS,
                                    env=child_env(), check=False)
        except subprocess.TimeoutExpired as e:
            raise SourceUnavailable(f"retrieval-client quote timed out after {RETRIEVAL_CLIENT_QUOTE_TIMEOUT_SECONDS} s") from e

    if result.returncode != 0:
        detail = (result.stderr.strip() or result.stdout.strip()).splitlines()[-1:] or [f"exit code {result.returncode}"]
        raise SourceUnavailable(detail[0])

    try:
        return parse_dry_run_quote(result.stdout, len(piece_cids))
    except ValueError as e:
        raise SourceUnavailable(f"unexpected retrieval-client output: {e}") from e


@utils.json_dataclass()
class RetrievalSource:
    base_url: str
    quote: RetrievalQuote  # exact quote for all pieces, from retrieval-client
    deal_id: int | None = None  # None for a manually given source URL
    provider_id: ActorId | None = None

    def is_free(self) -> bool:
        return self.quote.paid_pieces == 0


def http_base_from_multiaddr(addr: str) -> str | None:
    match = _HTTP_MULTIADDR.match(addr.strip())

    if not match:
        return None

    host, port, transport = match.groups()
    scheme = "https" if transport in ("https", "tls/http", "wss") else "http"
    host = f"[{host}]" if ":" in host else host
    return f"{scheme}://{host}:{port}"


# Like LPR retrieval-client's discovery: the miner's PeerId -> cid.contact provider addresses, else its on-chain multiaddrs
def discover_provider_http_bases(provider_id: ActorId) -> list[str]:
    peer_id = Web3Service().state_miner_info(provider_id).get("PeerId")
    bases = []

    if peer_id:
        # noinspection PyBroadException
        try:
            resp = requests.get(f"{CID_CONTACT_URL}/providers/{peer_id}", timeout=CID_CONTACT_TIMEOUT_SECONDS)
            if resp.ok:
                bases = [base for base in (http_base_from_multiaddr(addr) for addr in re.findall(r'"(/[^"]+)"', resp.text)) if base]

        # best effort, fall back to on-chain multiaddrs
        except requests.RequestException as e:
            logger.warning("cid.contact lookup for %s failed: %s", provider_id, e)

    if not bases:
        try:
            bases = CurioMarketDiscovery.get_market_urls(provider_id)
        except RuntimeError:
            bases = []

    return list(dict.fromkeys(bases))


# exact quote for every piece at base_url, or None with the reason the source can't serve the dataset
def quote_source(base_url: str, pieces: list[dict]) -> tuple[RetrievalSource | None, str]:
    try:
        commands_utils.validate_and_parse_url(base_url)  # same private-address guard as for manifests: endpoints are advertised by SPs
    except (click.ClickException, OSError) as e:
        return None, str(e)

    try:
        quote = quote_retrieval(base_url, [piece["pieceCid"] for piece in pieces])
    except SourceUnavailable as e:
        return None, str(e)

    # noinspection PyArgumentList
    return RetrievalSource(base_url=base_url, quote=quote), "ok"


# Piece-set commitment of a deal's dataset (see the header), or None when it can't be established (e.g. its manifest is gone)
def deal_dataset(view: PoRepMarketDealView) -> HexBytes | None:
    if commands_utils.get_evidence_type(view.deal.evidence_adapter_address) == EvidenceType.SECTOR_PLACEMENT:
        return HexBytes(view.data.manifest_hash)

    try:
        manifest, raw_manifest = commands_utils.fetch_manifest(view.data.manifest_location, show_manifest=False, quiet=True)
    except click.ClickException:
        return None

    if bytes(commands_utils.hash_manifest(raw_manifest)) != bytes(view.data.manifest_hash):
        return None  # the manifest changed since the deal was proposed

    return PieceSet(manifest[0]["pieces"]).commitment()


# whether the deal's evidence adapter holds evidence that the data is stored
def _has_storage_evidence(view: PoRepMarketDealView) -> bool:
    if commands_utils.get_evidence_type(view.deal.evidence_adapter_address) == EvidenceType.VERIF_REG_CLAIMS:
        return bool(commands_utils.get_deal_claim_ids(view.deal))

    return view.deal.state == PoRepMarketDealState.ACTIVE  # sector placement deals activate once every piece is accepted


def find_healthy_source(pieces: list[dict],
                        exclude_provider_ids: set[ActorId],
                        source_url: str | None = None) -> RetrievalSource:
    #
    if source_url:
        source, reason = quote_source(source_url.rstrip("/"), pieces)
        if not source:
            raise click.ClickException(f"Source {source_url} is not serving the dataset: {reason}")

        click.echo(f"Using source {source.base_url}: {_price_str(source)}")
        return source

    click.echo("\nLooking for a healthy SP still serving this dataset (same piece set, other providers)...")
    dataset = PieceSet(pieces).commitment()
    size_bytes = PieceSet(pieces).size_bytes
    candidates = []

    # full deal views in pages of 100: one RPC call per page instead of one per deal
    for view in PoRepMarketViewHelper().get_deal_views():
        if (view.deal.state != PoRepMarketDealState.ACTIVE
                or view.terms.requested_size_bytes != size_bytes  # cheap filter before fetching DataCap deals' manifests
                or view.deal.provider_id in exclude_provider_ids
                or view.deal.provider_id in (c.deal.provider_id for c in candidates)):
            continue

        if deal_dataset(view) == dataset:
            candidates.append(view)

    sources = []

    for view in candidates:
        label = f"  deal {view.deal.deal_id} provider {view.deal.provider_id}"

        if view.deal.deal_type != PoRepMarketDealType.PUBLIC:
            click.echo(f"{label}: skipped, {view.deal.deal_type} deal (LPR only serves private deals to their owner)")
            continue

        if not _has_storage_evidence(view):
            click.echo(f"{label}: skipped, no storage evidence on-chain")
            continue

        try:
            bases = discover_provider_http_bases(view.deal.provider_id)
        except RuntimeError as e:
            click.echo(f"{label}: skipped, {e}")
            continue

        if not bases:
            click.echo(f"{label}: skipped, no advertised HTTP endpoint")
            continue

        for base_url in bases:
            source, reason = quote_source(base_url, pieces)

            if source:
                source.deal_id, source.provider_id = view.deal.deal_id, view.deal.provider_id
                click.echo(f"{label} at {base_url}: healthy, {_price_str(source)}")
                sources.append(source)
                break

            click.echo(f"{label} at {base_url}: not serving, {reason}")

    if not sources:
        raise click.ClickException("No healthy SP found serving this dataset; pass a source URL explicitly if you know one")

    # same preference as LPR retrieval-client: free first, then cheapest
    return min(sources, key=lambda s: s.quote.total)


def _price_str(source: RetrievalSource) -> str:
    return "free" if source.is_free() else f"{source.quote.total} USDFC for {source.quote.paid_pieces} paid piece(s)"


# Shared by the client, who funds the repair retrieval, and the new SP, who spends it: both must use the same FileCoinPay
# account (the deal's SP payee) and token (the deal's payment token), or the deposit lands where the retrieval can't use it.
def resolve_repair_payee(deal: PoRepMarketDealView) -> EthAddress:
    payee = deal.payment.payee

    if int(payee, 16) == 0:
        payee = SPRegistry().get_provider_view(deal.deal.provider_id).payee_address

    if int(payee, 16) == 0:
        raise click.ClickException(f"No payee address found for deal ID {deal.deal.deal_id} provider {deal.deal.provider_id}")

    # retrieval-client signs with a plain secp256k1 key, so a contract payee (e.g. multisig) cannot retrieve
    if Web3Service().w3().eth.get_code(payee):
        raise click.ClickException(f"Deal ID {deal.deal.deal_id} payee {payee} is a contract; "
                                   f"the repair retrieval needs an externally owned payee wallet.")

    return EthAddress(payee)


# Repair retrievals are paid in USDFC: an LPR sp-proxy only credits Filecoin Pay rails in its own payment token, the chain's
# USDFC. Same lookup as LPR retrieval-client: the SP_PROXY_PAY_TOKEN_ADDRESS override (needed on local devnets), else the
# chain's known USDFC address (go-synapse constants). retrieval-client inherits the same variable from the environment.
USDFC_ADDRESSES_BY_CHAIN_ID = {
    314: "0x80B98d3aa09ffff255c3ba4A241111Ff1262F045",  # mainnet
    314159: "0xb3042734b608a1B16e9e86B374A3f3e389B4cDf0",  # calibration
}


def usdfc_token() -> EthAddress:
    override = utils.get_env("SP_PROXY_PAY_TOKEN_ADDRESS")

    if override:
        # f410/t410 overrides need the conversion; plain 0x addresses don't (and need no RPC call)
        return EthAddress(override) if override.startswith("0x") else EthAddress.from_any(override)

    chain_id = Web3Service().get_chain_id()

    if chain_id not in USDFC_ADDRESSES_BY_CHAIN_ID:
        raise click.ClickException(f"Unknown USDFC token for chain ID {chain_id}; set SP_PROXY_PAY_TOKEN_ADDRESS")

    return EthAddress(USDFC_ADDRESSES_BY_CHAIN_ID[chain_id])


# The client's deposit and the new SP's retrieval both use the deal's payment token, so only USDFC deals can be repaired
def ensure_usdfc(token: EthAddress, subject: str):
    usdfc = usdfc_token()

    if EthAddress(token) != usdfc:
        raise click.ClickException(f"{subject} pays in token {token}, not USDFC ({usdfc}). Repair retrievals are paid in USDFC, "
                                   f"the token large-paid-retrievals sp-proxies settle in, so only USDFC deals can be repaired.")


def repair_payment_token(deal: PoRepMarketDealView) -> EthAddress:
    token = EthAddress(deal.payment.payment_token)
    ensure_usdfc(token, f"Deal ID {deal.deal.deal_id}")
    return token
