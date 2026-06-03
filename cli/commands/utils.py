import ipaddress
import json
import socket
from pathlib import Path
from urllib.parse import ParseResult
from urllib.parse import urlparse

import click
import requests
from eth_account.types import PrivateKeyType

from cli import utils
from cli._cli import is_dry_run
from cli.services.contracts.client_contract import ClientContract
from cli.services.contracts.erc20_contract import ERC20Contract
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.porep_market import PoRepMarketDealState, PoRepMarketDealProposal, PoRepMarket
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.web3_service import EthAddress, ActorId
from cli.services.web3_service import Web3Service


def get_all_deals(state: PoRepMarketDealState | str | None = None,
                  organization: EthAddress | None = None) -> list[PoRepMarketDealProposal]:
    #
    _state = PoRepMarketDealState.from_string(str(state)) if state else None

    if organization:
        # prefer get_deals_for_organization_by_state function when asking for organization...
        result = []
        selected_states = [_state] if _state else list(PoRepMarketDealState)

        for selected_state in selected_states:
            result.extend(PoRepMarket().get_deals_for_organization_by_state(organization, selected_state))
    else:
        # ... otherwise prefer get_all_deals function
        result = PoRepMarket().get_deals()

        if _state:
            result = [deal for deal in result if deal.state == _state]

    return result


def get_client_deals(_client_address: EthAddress,
                     state: PoRepMarketDealState | None = None) -> list[PoRepMarketDealProposal]:
    all_deals = get_all_deals(state)
    return [deal for deal in all_deals if deal.client_address == _client_address]


def get_sp_deals(state: PoRepMarketDealState | None = None,
                 organization_address: EthAddress | None = None,
                 provider_id: ActorId | None = None) -> list[PoRepMarketDealProposal]:
    #
    if provider_id:
        assert not organization_address

        try:
            provider_info = SPRegistry().get_provider_info(provider_id)
        except RuntimeError:
            return []

        organization_address = provider_info.organization_address

    assert organization_address
    result = get_all_deals(state, organization_address)

    if provider_id:
        result = [deal for deal in result if deal.provider_id == provider_id]

    return result


def get_deal_allocations(deal: PoRepMarketDealProposal) -> dict[str, dict]:
    deal_allocations = ClientContract().get_client_allocation_ids_per_deal(deal.deal_id)

    allocations = Web3Service().state_get_allocations(ClientContract().address().to_actor_id())
    return {allocation_id: allocation for allocation_id, allocation in allocations.items() if int(allocation_id) in deal_allocations}


def get_deal_claims(deal: PoRepMarketDealProposal) -> dict[str, dict]:
    deal_allocations = ClientContract().get_client_allocation_ids_per_deal(deal.deal_id)

    claims = Web3Service().state_get_claims(deal.provider_id, ClientContract().address().to_actor_id())
    return {claim_id: claim for claim_id, claim in claims.items() if int(claim_id) in deal_allocations}


def print_info():
    # noinspection PyBroadException
    try:
        click.echo(f"Chain ID: {Web3Service().get_chain_id()}")

    # pylint: disable=broad-exception-caught
    except Exception as e:
        click.echo(f"Error getting chain ID: {e}\n")

    click.echo(f"RPC_URL={utils.get_env('RPC_URL', required=False)}")
    click.echo()
    click.echo(f"POREP_MARKET={utils.get_env('POREP_MARKET', required=False)}")
    click.echo(f"FILECOIN_PAY={utils.get_env('FILECOIN_PAY', required=False)}")
    click.echo(f"USDC_TOKEN={utils.get_env('USDC_TOKEN', required=False)}")
    click.echo()
    click.echo(f"DRY_RUN={is_dry_run()}")
    click.echo(f"DEBUG={utils.get_env_required('DEBUG', default='False').capitalize()}")


# retries = None means "ask user"
def fetch_manifest(manifest_url: str,
                   show_manifest: bool | None = None,
                   retries: int | None = None,
                   quiet: bool = False) -> list[dict]:
    #
    if not quiet:
        click.echo(f"Fetching manifest from {manifest_url}")

    parsed_url = validate_and_parse_url(manifest_url)

    while True:
        try:
            return _fetch_manifest(parsed_url, show_manifest, quiet)
        except requests.exceptions.RequestException as e:
            if retries is None:
                if not utils.confirm(f"\nFailed to fetch manifest:\n{e}.\nRetry?", default=True):
                    raise click.ClickException(f"Network error while fetching manifest: {e}") from e

            else:
                # noinspection PyUnresolvedReferences
                if retries <= 0:
                    raise click.ClickException(f"Network error while fetching manifest: {e}") from e
                else:
                    if not quiet:
                        click.echo(f"Retrying... ({retries} retries left)")

                    retries -= 1


def fetch_local_manifest(manifest_path: Path) -> list[dict]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as e:
        raise click.ClickException(f"Failed to read manifest file: {e}") from e
    except ValueError as e:
        raise click.ClickException(f"Manifest is not a valid JSON: {e}") from e

    return _validate_manifest(manifest)


def validate_and_parse_url(manifest_url: str) -> ParseResult:
    parsed = urlparse(manifest_url)

    if not parsed.hostname:
        raise click.ClickException("Manifest URL must have a hostname")

    if parsed.scheme not in ("http", "https"):
        raise click.ClickException("Manifest URL must use http/https")

    # noinspection PyTypeChecker
    ip = socket.gethostbyname(parsed.hostname)
    addr = ipaddress.ip_address(ip)

    if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local or addr.is_multicast:
        raise click.ClickException(f"Manifest URL resolves to a disallowed IP address: {ip}")

    return parsed


def _fetch_manifest(parsed_url: ParseResult,
                    show_manifest: bool | None = None,
                    quiet: bool = False) -> list[dict]:
    resp = requests.get(parsed_url.geturl(), headers={"Host": parsed_url.hostname}, timeout=30, allow_redirects=False)
    resp.raise_for_status()

    if not quiet:
        click.echo("Manifest downloaded")

    try:
        manifest = resp.json()
    except ValueError as e:
        raise click.ClickException(f"Manifest is not a valid JSON: {e}") from e

    if show_manifest or (show_manifest is None and utils.confirm("Show manifest?")):
        _manifest = utils.json_pretty(manifest)
        click.echo_via_pager("\n".join([f"{i + 1}. {line}" for i, line in enumerate(_manifest.splitlines())]))
        click.echo()

    return _validate_manifest(manifest)


def _validate_manifest(manifest: object) -> list[dict]:
    MINIMUM_DAG_PIECE_SIZE_BYTES = 1024 * 1024  # 1 MiB

    try:
        # validate manifest format
        if not (
                manifest and
                isinstance(manifest, list) and
                len(manifest) == 1 and

                manifest[0] and
                isinstance(manifest[0], dict) and
                "pieces" in manifest[0] and

                manifest[0]["pieces"] and
                isinstance(manifest[0]["pieces"], list) and

                all(isinstance(piece, dict) and
                    "pieceCid" in piece and
                    "pieceType" in piece and
                    "pieceSize" in piece and
                    "preparationId" in piece and
                    "attachmentId" in piece and
                    "storagePath" in piece
                    for piece in manifest[0]["pieces"])
        ):
            raise click.ClickException("Invalid manifest format")

        # validate manifest pieces
        pieces = manifest[0]["pieces"]
        data_pieces = [piece for piece in pieces if piece["pieceType"] == "data"]
        dag_pieces = [piece for piece in pieces if piece["pieceType"] == "dag"]

        if len(pieces) <= 1 or len(data_pieces) != len(pieces) - 1 or len(dag_pieces) != 1:
            raise click.ClickException("Invalid manifest pieces: must contain exactly one dag piece and at least one data piece")

        if not all(piece["preparationId"] == pieces[0]["preparationId"] for piece in pieces):
            raise click.ClickException("Invalid preparationId in manifest pieces: must be the same for all pieces")

        if not all(piece["attachmentId"] == pieces[0]["attachmentId"] for piece in pieces):
            raise click.ClickException("Invalid attachmentId in manifest pieces: must be the same for all pieces")

        if dag_pieces[0]["pieceSize"] < MINIMUM_DAG_PIECE_SIZE_BYTES:
            raise click.ClickException(f"Invalid dag piece size in manifest: must be at least 1 MiB "
                                       f"({dag_pieces[0]['pieceSize']} < {MINIMUM_DAG_PIECE_SIZE_BYTES} bytes)")
        #
    except KeyError as e:
        raise click.ClickException(f"Invalid manifest format: missing key {e}") from e

    return manifest


def get_filecoinpay_account(token_address: str, owner_address: EthAddress):
    _token_address = EthAddress(token_address)
    token = ERC20Contract(_token_address)
    token_symbol = token.symbol()
    token_decimals = token.decimals()
    account = FileCoinPay().get_account(_token_address, owner_address)

    return {
        "owner": str(owner_address),
        "token": {
            "address": str(_token_address),
            "name": token.name(),
            "symbol": token_symbol,
            "decimals": token_decimals,
            "balance": f"{utils.str_from_wei(token.balance_of(owner_address), token_decimals)} {token_symbol}"
        },
        "account": {
            "funds": f"{utils.str_from_wei(account.funds, token_decimals)} {token_symbol}",
            "account": account.__dict__
        }
    }


def reject_deal(deal: PoRepMarketDealProposal, from_private_key: PrivateKeyType, confirm_session_id: str | None = None) -> str:
    if deal.state != PoRepMarketDealState.PROPOSED:
        raise click.ClickException(f"Deal ID {deal.deal_id} is in state {deal.state} != PROPOSED")

    utils.confirm(f"Rejecting deal ID {deal.deal_id}: {deal}", default=True, abort=True, session_id=confirm_session_id)

    tx_hash = PoRepMarket().reject_deal(deal.deal_id, from_private_key)
    click.echo(f"Deal ID {deal.deal_id} rejected: {tx_hash}")

    return tx_hash
