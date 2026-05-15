import ipaddress
import socket
from typing import Dict
from urllib.parse import ParseResult
from urllib.parse import urlparse

import click
import requests
from eth_account.types import PrivateKeyType

from cli import utils
from cli._cli import is_dry_run
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


def get_client_deals(_client_address: EthAddress, state: PoRepMarketDealState | None = None) -> list[PoRepMarketDealProposal]:
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
    click.echo(f"CLIENT_CONTRACT={utils.get_env('CLIENT_CONTRACT', required=False)}")
    click.echo(f"SP_REGISTRY={utils.get_env('SP_REGISTRY', required=False)}")
    click.echo(f"VALIDATOR_FACTORY={utils.get_env('VALIDATOR_FACTORY', required=False)}")
    click.echo(f"FILECOIN_PAY={utils.get_env('FILECOIN_PAY', required=False)}")
    click.echo(f"USDC_TOKEN={utils.get_env('USDC_TOKEN', required=False)}")
    click.echo()
    click.echo(f"DRY_RUN={is_dry_run()}")
    click.echo(f"DEBUG={utils.get_env_required('DEBUG', default='False').capitalize()}")


def validate_address_matches_private_key(address: EthAddress, private_key: PrivateKeyType | None):
    if not private_key:
        raise click.ClickException("Private key is not set")

    derived_address = EthAddress.from_private_key(private_key)

    if derived_address != address:
        raise click.ClickException(f"Address {address} does not match private key {utils.private_str_to_log_str(private_key)} (expected: {derived_address})")


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


def _fetch_manifest(parsed_url: ParseResult, show_manifest: bool | None = None, quiet: bool = False) -> list[dict]:
    MINIMUM_DAG_PIECE_SIZE_BYTES = 1024 * 1024  # 1 MiB

    # download manifest
    resp = requests.get(parsed_url.geturl(), headers={"Host": parsed_url.hostname}, timeout=30, allow_redirects=False)
    resp.raise_for_status()

    try:
        manifest = resp.json()
    except ValueError as e:
        raise click.ClickException(f"Manifest is not a valid JSON: {e}") from e

    if not quiet:
        click.echo("Manifest downloaded")

    # show manifest
    if show_manifest or (show_manifest is None and utils.confirm("Show manifest?")):
        _manifest = utils.json_pretty(manifest)
        click.echo_via_pager("\n".join([f"{i + 1}. {line}" for i, line in enumerate(_manifest.splitlines())]))
        click.echo()

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


def match_deal_allocations(manifest_pieces: list[dict],
                           state_allocations: Dict[str, dict],
                           client_allocations: list[int]) -> list[dict]:
    #
    manifest_cids = {p["pieceCid"] for p in manifest_pieces}

    return [
        {"allocationId": alloc_id, "CID": state_allocations[str(alloc_id)].get("Data", {}).get("/")}
        for alloc_id in client_allocations
        if str(alloc_id) in state_allocations and state_allocations[str(alloc_id)].get("Data", {}).get("/") in manifest_cids
    ]
