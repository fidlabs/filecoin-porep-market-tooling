import ipaddress
import json
import socket
from pathlib import Path
from urllib.parse import ParseResult, urlparse

import click
import requests
from requests import RequestException

from cli import utils
from cli._cli import is_dry_run
from cli.services.contracts.datacap_evidence_adapter import DataCapEvidenceAdapter
from cli.services.contracts.erc20_contract import ERC20Contract
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.porep_market import (
    PoRepMarket,
    PoRepMarketDeal,
    PoRepMarketDealState,
)
from cli.services.contracts.sp_registry import SPRegistry, SPRegistryProviderInput, SPRegistryProviderView, SPRegistryOfferInput
from cli.services.contracts.validator_factory import ValidatorFactory
from cli.services.txsigner import TxSigner
from cli.services.web3_service import ActorId, EthAddress, FilAddress, Web3Service

_EVIDENCE_IDS_PAGE_SIZE = 500


def get_all_deals(state: PoRepMarketDealState | None = None,
                  organization: EthAddress | None = None) -> list[PoRepMarketDeal]:
    #
    if organization:
        # prefer get_deals_for_organization_by_state function when asking for organization...
        result = []
        selected_states = [state] if state else list(PoRepMarketDealState)

        for selected_state in selected_states:
            result.extend(PoRepMarket().get_deals_for_organization_by_state(organization, selected_state))
    else:
        # ... otherwise prefer get_deals function
        result = PoRepMarket().get_deals()

        if state:
            result = [deal for deal in result if deal.state == state]

    return result


def get_client_deals(_client_address: EthAddress, state: PoRepMarketDealState | None = None) -> list[PoRepMarketDeal]:
    all_deals = get_all_deals(state)
    return [deal for deal in all_deals if deal.client_address == _client_address]


def get_sp_deals(state: PoRepMarketDealState | None = None,
                 organization_address: EthAddress | None = None,
                 provider_id: ActorId | None = None) -> list[PoRepMarketDeal]:
    #
    if provider_id:
        assert not organization_address

        try:
            provider_info = SPRegistry().get_provider_view(provider_id)
        except RuntimeError:
            return []

        organization_address = provider_info.organization_address

    assert organization_address
    result = get_all_deals(state, organization_address)

    if provider_id:
        result = [deal for deal in result if deal.provider_id == provider_id]

    return result


def get_deal_allocation_ids(deal: PoRepMarketDeal) -> list[int]:
    adapter = DataCapEvidenceAdapter(deal.evidence_adapter_address)

    ids: list[int] = []
    offset = 0

    while True:
        page, total = adapter.get_allocation_ids_per_deal(deal.deal_id, offset, _EVIDENCE_IDS_PAGE_SIZE)
        ids.extend(int(allocation_id) for allocation_id in page)
        offset += len(page)

        if not page or offset >= total:
            return ids


def get_deal_claim_ids(deal: PoRepMarketDeal) -> list[int]:
    adapter = DataCapEvidenceAdapter(deal.evidence_adapter_address)

    ids: list[int] = []
    offset = 0

    while True:
        page, total = adapter.get_claim_ids(deal.deal_id, offset, _EVIDENCE_IDS_PAGE_SIZE)
        ids.extend(int(claim_id) for claim_id in page)
        offset += len(page)

        if not page or offset >= total:
            return ids


def get_deal_allocations(deal: PoRepMarketDeal) -> dict[str, dict]:
    deal_allocations = get_deal_allocation_ids(deal)

    allocations = Web3Service().state_get_allocations(deal.evidence_adapter_address.to_actor_id())
    return {allocation_id: allocation for allocation_id, allocation in allocations.items() if int(allocation_id) in deal_allocations}


def get_deal_claims(deal: PoRepMarketDeal) -> dict[str, dict]:
    deal_claims = get_deal_claim_ids(deal)

    claims = Web3Service().state_get_claims(deal.provider_id, deal.evidence_adapter_address.to_actor_id())
    return {claim_id: claim for claim_id, claim in claims.items() if int(claim_id) in deal_claims}


# pylint: disable=broad-exception-caught
def print_info(account_address: EthAddress | None = None, account_name: str = "Account"):
    if account_address:
        click.echo(f"{account_name} wallet eth-address: {account_address}")

        try:
            click.echo(f"{account_name} wallet f-address: {FilAddress.from_any(account_address)}")
        except Exception as e:
            click.echo(f"Error converting account address to Filecoin format: {e}")

        try:
            click.echo(f"{account_name} wallet actor ID: {ActorId.from_any(account_address)}")
        except Exception as e:
            click.echo(f"Error converting account address to Actor ID format: {e}")

        try:
            click.echo(f"{account_name} wallet FIL balance: {utils.str_from_wei(Web3Service().wallet_balance(account_address), utils.FIL_TOKEN_DECIMALS)} FIL")
        except Exception as e:
            click.echo(f"Error fetching account FIL balance: {e}")

        click.echo()

    try:
        click.echo(f"Chain ID: {Web3Service().get_chain_id()} ({Web3Service().get_network_name()})")
    except Exception as e:
        click.echo(f"Error fetching chain ID: {e}")

    click.echo(f"RPC_URL={utils.get_env('RPC_URL', required=False)}")
    click.echo()
    click.echo(f"POREP_MARKET_VIEW_HELPER={utils.get_env('POREP_MARKET_VIEW_HELPER', required=False)}")
    click.echo(f"FILECOIN_PAY={utils.get_env('FILECOIN_PAY', required=False)}")
    click.echo(f"USDC_TOKEN={utils.get_env('USDC_TOKEN', required=False)}")

    try:
        click.echo(f"POREP_MARKET={PoRepMarket().address()}")
    except Exception as e:
        click.echo(f"Error fetching PoRep Market address: {e}")

    try:
        click.echo(f"SP_REGISTRY={SPRegistry().address()}")
    except Exception as e:
        click.echo(f"Error fetching SP Registry address: {e}")

    try:
        click.echo(f"VALIDATOR_FACTORY={ValidatorFactory().address()}")
    except Exception as e:
        click.echo(f"Error fetching Validator Factory address: {e}")

    try:
        click.echo(f"EVIDENCE_ADAPTER={DataCapEvidenceAdapter().address()}")
    except Exception as e:
        click.echo(f"Error fetching Evidence Adapter address: {e}")

    click.echo()
    click.echo(f"DRY_RUN={is_dry_run()}")
    click.echo(f"DEBUG={utils.get_env_required('DEBUG', default='False').capitalize()}")


# retries = None means "ask user"
def fetch_manifest(manifest_url: str,
                   show_manifest: bool | None = None,
                   retries: int | None = None,
                   quiet=False) -> tuple[list[dict], bytes]:
    #
    if not quiet:
        click.echo(f"Fetching manifest from {manifest_url}")

    parsed_url = validate_and_parse_url(manifest_url)

    while True:
        try:
            return _fetch_manifest(parsed_url, show_manifest, quiet)
        except RequestException as e:
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


def fetch_local_manifest(manifest_path: Path, quiet=False) -> tuple[list[dict], bytes]:
    try:
        raw_manifest = manifest_path.read_bytes()
        manifest = json.loads(raw_manifest.decode("utf-8"))
    except OSError as e:
        raise click.ClickException(f"Failed to read manifest file: {e}") from e
    except ValueError as e:
        raise click.ClickException(f"Manifest is not a valid JSON: {e}") from e

    return _validate_manifest(manifest, quiet), raw_manifest


def _private_manifest_urls_allowed() -> bool:
    return utils.string_to_bool(utils.get_env("ALLOW_PRIVATE_MANIFEST_URLS", default="false")) or False


def validate_and_parse_url(manifest_url: str) -> ParseResult:
    parsed = urlparse(manifest_url)

    if not parsed.hostname:
        raise click.ClickException("Manifest URL must have a hostname")

    if parsed.scheme not in ("http", "https"):
        raise click.ClickException("Manifest URL must use http/https")

    # SSRF guard; ALLOW_PRIVATE_MANIFEST_URLS=true disables it for local devnets
    if not _private_manifest_urls_allowed():
        # noinspection PyTypeChecker
        ip = socket.gethostbyname(parsed.hostname)
        addr = ipaddress.ip_address(ip)

        if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local or addr.is_multicast:
            raise click.ClickException(f"Manifest URL resolves to a disallowed IP address: {ip}")

    return parsed


def _fetch_manifest(parsed_url: ParseResult, show_manifest: bool | None = None, quiet=False) -> tuple[list[dict], bytes]:
    resp = requests.get(parsed_url.geturl(), headers={"Host": parsed_url.hostname}, timeout=30, allow_redirects=False)

    # don't retry on 4xx errors
    if 400 <= resp.status_code < 500:
        raise click.ClickException(f"Failed to fetch manifest: {resp.status_code} {resp.reason} - {resp.text}")

    resp.raise_for_status()

    if not quiet:
        click.echo("Manifest downloaded")

    try:
        manifest = resp.json()
        raw_manifest = resp.content
    except ValueError as e:
        raise click.ClickException(f"Manifest is not a valid JSON: {e}") from e

    if show_manifest or (show_manifest is None and utils.confirm("Show manifest?")):
        _manifest = utils.json_pretty(manifest)
        click.echo_via_pager("\n".join([f"{i + 1}. {line}" for i, line in enumerate(_manifest.splitlines())]))
        click.echo()

    return _validate_manifest(manifest, quiet), raw_manifest


def _validate_manifest(manifest: object, quiet=False) -> list[dict]:
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
                    "fileSize" in piece and
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

        if not quiet:
            click.echo(f"Found {len(data_pieces)} data piece(s) and {len(dag_pieces)} dag piece(s), {len(pieces)} total")

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


def get_filecoinpay_account(token_address: EthAddress, owner_address: EthAddress):
    token = ERC20Contract(token_address)
    token_symbol = token.symbol()
    token_decimals = token.decimals()
    account = FileCoinPay().get_account(token_address, owner_address)

    return {
        "owner": str(owner_address),
        "token": {
            "address": str(token_address),
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


def withdraw_from_filecoinpay(to_address: str, amount: float, token_address: EthAddress, from_address: EthAddress, signer: TxSigner) -> str:
    _to_address = EthAddress.from_any(to_address)

    token = ERC20Contract(token_address)
    token_decimals = token.decimals()
    token_symbol = token.symbol()

    def print_token_balance(_account_address: EthAddress):
        token_balance = token.balance_of(_account_address)
        token_balance_str = utils.str_from_wei(token_balance, token_decimals)

        click.echo(f"Token balance of {_account_address}: {token_balance_str} {token_symbol}")
        click.echo()

    print_token_balance(_to_address)
    click.echo(f"FileCoinPay account of {from_address}: " + utils.json_pretty(get_filecoinpay_account(token_address, from_address)))
    click.echo()

    _amount = utils.to_wei(amount, token_decimals)
    amount_str = utils.str_from_wei(_amount, token_decimals)

    utils.confirm(f"Withdraw {amount_str} {token_symbol} from {from_address} FileCoinPay account to {_to_address}?", abort=True)

    tx_hash = FileCoinPay().withdraw_to(token_address,
                                        _to_address,
                                        _amount,
                                        signer)

    click.echo(f"Withdraw transaction sent: {tx_hash}")
    print_token_balance(_to_address)
    return tx_hash


def reject_deal(deal: PoRepMarketDeal, signer: TxSigner, confirm_session_id: str | None = None) -> str:
    # deals are created directly in ACCEPTED state (offer match == acceptance);
    # they can be rejected while no FileCoinPay rail is set yet. PROPOSED is kept
    # for deals predating the auto-accept contract.

    if deal.state not in (PoRepMarketDealState.PROPOSED, PoRepMarketDealState.ACCEPTED):
        raise click.ClickException(f"Deal ID {deal.deal_id} is in state {deal.state} != PROPOSED/ACCEPTED")

    if deal.state == PoRepMarketDealState.ACCEPTED and deal.rail_id:
        raise click.ClickException(f"Deal ID {deal.deal_id} already has FileCoinPay rail {deal.rail_id} set and cannot be rejected")

    utils.confirm(f"Rejecting deal ID {deal.deal_id}: {deal}", default=True, abort=True, session_id=confirm_session_id)

    if deal.state == PoRepMarketDealState.ACCEPTED:
        tx_hash = PoRepMarket().reject_accepted_deal(deal.deal_id, signer)
    else:
        tx_hash = PoRepMarket().reject_deal(deal.deal_id, signer)

    click.echo(f"Deal ID {deal.deal_id} rejected: {tx_hash}")
    return tx_hash


def pause_sp(provider_id: ActorId, signer: TxSigner) -> str:
    provider = SPRegistry().get_provider_view(provider_id)

    if provider.paused:
        raise click.ClickException(f"Storage Provider {provider.provider_id} is already paused")

    utils.confirm(f"Pausing Storage Provider {provider.provider_id}: "
                  f"{utils.json_pretty(provider)}", abort=True)

    tx_hash = SPRegistry().pause_provider(provider.provider_id, signer)
    click.echo(f"Storage Provider {provider.provider_id} paused: {tx_hash}")
    return tx_hash


def unpause_sp(provider_id: ActorId, signer: TxSigner) -> str:
    provider = SPRegistry().get_provider_view(provider_id)

    if not provider.paused:
        raise click.ClickException(f"Storage Provider {provider.provider_id} is not paused")

    utils.confirm(f"Unpausing Storage Provider {provider.provider_id}: "
                  f"{utils.json_pretty(provider)}", abort=True)

    tx_hash = SPRegistry().unpause_provider(provider.provider_id, signer)
    click.echo(f"Storage Provider {provider.provider_id} unpaused: {tx_hash}")
    return tx_hash


def block_sp(provider_id: ActorId, signer: TxSigner) -> str:
    provider = SPRegistry().get_provider_view(provider_id)

    if provider.blocked:
        raise click.ClickException(f"Storage Provider {provider.provider_id} is already blocked")

    utils.confirm(f"Blocking Storage Provider {provider.provider_id}: "
                  f"{utils.json_pretty(provider)}", abort=True)

    tx_hash = SPRegistry().block_provider(provider.provider_id, signer)
    click.echo(f"Storage Provider {provider.provider_id} blocked: {tx_hash}")
    return tx_hash


def unblock_sp(provider_id: ActorId, signer: TxSigner) -> str:
    provider = SPRegistry().get_provider_view(provider_id)

    if not provider.blocked:
        raise click.ClickException(f"Storage Provider {provider.provider_id} is not blocked")

    utils.confirm(f"Unblocking Storage Provider {provider.provider_id}: "
                  f"{utils.json_pretty(provider)}", abort=True)

    tx_hash = SPRegistry().unblock_provider(provider.provider_id, signer)
    click.echo(f"Storage Provider {provider.provider_id} unblocked: {tx_hash}")
    return tx_hash


def _update_sp_params(provider_info: SPRegistryProviderInput,
                      registered_info: SPRegistryProviderView,
                      signer: TxSigner):
    #
    if provider_info.organization_address != registered_info.organization_address:
        if not utils.confirm(f"\norganization_address cannot be updated for Storage Provider {provider_info.provider_id}, "
                             f"continue with other parameters?",
                             default=True):
            #
            click.echo("Skipped this SP")
            return

    if provider_info.payee_address != registered_info.payee_address:
        if utils.confirm(f"\nUpdating payee_address for Storage Provider {provider_info.provider_id}: "
                         f"Current: {registered_info.payee_address} -> New: {provider_info.payee_address}",
                         default=True,
                         session_id=f"update-{provider_info.provider_id}"):
            #
            tx_hash = SPRegistry().set_payee(provider_info.provider_id,
                                             provider_info.payee_address,
                                             signer)

            click.echo(f"Updated payee_address for Storage Provider {provider_info.provider_id}: {tx_hash}")

        else:
            click.echo("Skipped this parameter\n")

    if provider_info.available_bytes != registered_info.available_bytes:
        if utils.confirm(f"\nUpdating available_bytes for Storage Provider {provider_info.provider_id}: "
                         f"Current: {registered_info.available_bytes} -> New: {provider_info.available_bytes}",
                         default=True,
                         session_id=f"update-{provider_info.provider_id}"):
            #
            tx_hash = SPRegistry().update_available_space(provider_info.provider_id,
                                                          provider_info.available_bytes,
                                                          signer)

            click.echo(f"Updated available_bytes for Storage Provider {provider_info.provider_id}: {tx_hash}")

        else:
            click.echo("Skipped this parameter\n")


def register_or_update_sps(providers: list[SPRegistryProviderInput], signer: TxSigner):
    for provider_info in providers:
        if SPRegistry().is_provider_registered(provider_info.provider_id):
            # update Storage Provider parameters if different from registered ones
            registered_info = SPRegistry().get_provider_view(provider_info.provider_id)

            # print only different parameters
            current_different_params = {k: getattr(registered_info, k) for k in provider_info.__dict__.keys() if
                                        getattr(registered_info, k) != getattr(provider_info, k)}
            new_different_params = {k: v for k, v in provider_info.__dict__.items() if getattr(registered_info, k) != v}
            assert current_different_params.keys() == new_different_params.keys()

            if not current_different_params:
                click.echo(f"Storage Provider {provider_info.provider_id} already registered with same parameters")
                continue

            if not utils.confirm(f"\nStorage Provider {provider_info.provider_id} already registered with different parameters. "
                                 f"Do you want to update the parameters?\n"
                                 f"Current: {utils.json_pretty(current_different_params)} -> New: {utils.json_pretty(new_different_params)}",
                                 session_id="update-provider"):
                #
                click.echo("Skipped this SP")
                continue

            _update_sp_params(provider_info, registered_info, signer)

        else:
            # register Storage Provider with given parameters

            if not utils.confirm(f"\nRegistering Storage Provider with parameters: {provider_info}", default=True, session_id="register-provider"):
                click.echo("Skipped this SP")
                continue

            if not utils.confirm(f"\nThe organization_address {provider_info.organization_address} cannot be changed "
                                 f"once registered for provider_id {provider_info.provider_id}. Are you sure this is correct?"):
                #
                click.echo("Skipped this SP")
                continue

            tx_hash = SPRegistry().register_provider_for(provider_info, signer)
            click.echo(f"Provider {provider_info.provider_id} registered: {tx_hash}")


# def _update_offer_params(offer: SPRegistryOfferInput,
#                          registered_info: SPRegistryOfferView,
#                          different_parameters: dict,
#                          signer: TxSigner):
#
#     assert offer.provider_id == registered_info.provider_id
#
# if (provider.max_deal_duration_days, provider.min_deal_duration_days) != (registered_info.max_deal_duration_days, registered_info.min_deal_duration_days):
#     _different_parameters = {k: v for k, v in different_parameters.items() if k in ["max_deal_duration_days", "min_deal_duration_days"]}
#
#     if utils.confirm(f"Updating (max_deal_duration_days, min_deal_duration_days) for Storage Provider {provider.provider_id}: "
#                      f"{_different_parameters}",
#                      default=True,
#                      session_id=f"update-{provider.provider_id}"):
#         #
#         tx_hash = SPRegistry().set_deal_duration_limits(provider.provider_id,
#                                                         provider.min_deal_duration_days,
#                                                         provider.max_deal_duration_days,
#                                                         admin_signer())
#
#         click.echo(f"Updated (max_deal_duration_days, min_deal_duration_days) for Storage Provider {provider.provider_id}: {tx_hash}")
#
#     else:
#         click.echo("Skipped this parameter\n")
#
# if provider.price_per_sector_per_month != registered_info.price_per_sector_per_month:
#     if utils.confirm(f"Updating price_per_sector_per_month for Storage Provider {provider.provider_id}: "
#                      f"{different_parameters['price_per_sector_per_month']}",
#                      default=True,
#                      session_id=f"update-{provider.provider_id}"):
#         #
#         tx_hash = SPRegistry().set_price(provider.provider_id,
#                                          provider.price_per_sector_per_month,
#                                          admin_signer())
#
#         click.echo(f"Updated price_per_sector_per_month for Storage Provider {provider.provider_id}: {tx_hash}")
#
#     else:
#         click.echo("Skipped this parameter\n")
#
# if provider.capabilities != registered_info.capabilities:
#     if utils.confirm(f"\nUpdating capabilities for Storage Provider {provider.provider_id}: "
#                      f"{utils.json_pretty(different_parameters['capabilities'])}",
#                      default=True,
#                      session_id=f"update-{provider.provider_id}"):
#         #
#         tx_hash = SPRegistry().set_capabilities(provider.provider_id,
#                                                 provider.capabilities,
#                                                 admin_signer())
#
#         click.echo(f"Updated capabilities for Storage Provider {provider.provider_id}: {tx_hash}")
#
#     else:
#         click.echo("Skipped this parameter\n")


def register_offers(offers: list[SPRegistryOfferInput], signer: TxSigner):
    # TODO ASAP support offer update
    utils.confirm_ok("Current version of CLI / Smart Contracts does not support updating existing offers. "
                     "Each offer in the SP Registry DB will be considered new. "
                     "Please double-check each offer before sumitting it on-chain.")

    for offer in offers:
        is_registered = False

        if is_registered:
            # update PoRep Market Offer parameters if different from registered ones
            # __update_offer_params
            pass
        else:
            # register PoRep Market Offer with given parameters

            if not utils.confirm(f"\nRegistering PoRep Market Offer with parameters: {offer}",
                                 default=True, session_id="register-offer"):
                click.echo("Skipped this offer")
                continue

            tx_hash = SPRegistry().create_offer(offer, signer)
            click.echo(f"Offer for provider {offer.provider_id} registered: {tx_hash}")
