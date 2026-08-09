import click
import humanfriendly
from hexbytes import HexBytes
from web3 import Web3

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.client import _utils as client_utils
from cli.commands.client._client import client_address, client_signer
from cli.services.contracts.erc20_contract import ERC20Contract
from cli.services.contracts.porep_market import (
    PoRepMarket,
    PoRepMarketDealRequest,
    PoRepMarketDealState,
    PoRepMarketSLIThresholds,
    PoRepMarketDealType,
)
from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper
from cli.services.contracts.usdc_token import USDCToken
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import EthAddress, Web3Service


def hash_manifest(raw_manifest: bytes) -> HexBytes:
    return Web3.keccak(text=raw_manifest.decode("utf-8"))


def _propose_deal(manifest_url: str,
                  retrievability_bps: int,
                  bandwidth_mbps: int,
                  price_per_tib_per_month: float,
                  duration_months: int,
                  latency_ms: int,
                  indexing_pct: int,
                  payment_token_address: EthAddress,
                  deal_type: PoRepMarketDealType):
    #
    SelfUpdateService.check_and_prompt(manual=False)

    if price_per_tib_per_month > 100:
        raise click.BadParameter("Price per TiB per month is too high. Please use decimal format (e.g., 1.5 for 1.5 USDC).")

    MBPS_TO_BYTES_PER_SECOND = 125_000  # 1 Mbps = 10^6 bits/s / 8 = 125 000 bytes/s
    manifest, raw_manifest = commands_utils.fetch_manifest(manifest_url)

    pieces = manifest[0]["pieces"]
    pieces_size_bytes = sum(piece.get("pieceSize", 0) for piece in pieces)

    if pieces_size_bytes <= 0:
        raise ValueError("Invalid deal size")

    click.echo(f"\nFound {len(pieces)} total pieces with total pieceSize "
               f"{humanfriendly.format_size(pieces_size_bytes)} = {humanfriendly.format_size(pieces_size_bytes, binary=True)} = "
               f"{utils.bytes_to_sectors(pieces_size_bytes, PoRepMarket().get_sector_size_bytes())} sectors "
               f"(including dag piece)")

    payment_token = ERC20Contract(payment_token_address)
    payment_token_decimals = payment_token.decimals()
    price_per_sector_per_month_wei = commands_utils.price_per_TiB_tokens_to_per_32_GiB_wei(price_per_tib_per_month, payment_token_decimals)

    # noinspection PyArgumentList
    deal_request = PoRepMarketDealRequest(
        manifest_hash=hash_manifest(raw_manifest),
        requested_size_bytes=pieces_size_bytes,
        max_price_per_32_gib_per_month=price_per_sector_per_month_wei,
        manifest_location=manifest_url,
        payment_token_address=payment_token_address,
        duration_days=duration_months * 30,  # PoRep Market smart contracts assumes month == 30 days
        deal_type=deal_type,
        required_slis=PoRepMarketSLIThresholds(
            retrievability_bps=retrievability_bps,
            bandwidth_bytes_per_second=bandwidth_mbps * MBPS_TO_BYTES_PER_SECOND,
            latency_ms=latency_ms,
            indexing_pct=indexing_pct,
        )
    )

    Web3Service().wait_for_pending_transactions(client_address())
    existing_deals = commands_utils.get_client_deals(client_address())

    # warn if any of existing client deals looks similar to the new deal proposal
    for existing_deal in existing_deals:
        is_active = existing_deal.state in [PoRepMarketDealState.PROPOSED, PoRepMarketDealState.ACCEPTED, PoRepMarketDealState.ACTIVE]
        existing_deal_view = PoRepMarketViewHelper().get_deal_view(existing_deal.deal_id)

        if deal_request.requested_size_bytes == existing_deal_view.terms.requested_size_bytes:
            utils.confirm(f"\nWARNING: Client deal with the same deal size "
                          f"already exists in PoRep Market: {utils.json_pretty(existing_deal)} "
                          "Continue?", default=not is_active, abort=True)

        if deal_request.manifest_location == existing_deal_view.data.manifest_location:
            utils.confirm(
                f"\nWARNING: Client deal with the same manifest location "
                f"already exists in PoRep Market: {utils.json_pretty(existing_deal)} "
                "Continue?", default=not is_active, abort=True)

    payment_token_symbol = payment_token.symbol()
    deal_duration_months = deal_request.duration_days // 30  # PoRep Market smart contracts assumes month == 30 days

    max_cost_per_month = client_utils.calculate_deposit_amount(deal_request.requested_size_bytes,
                                                               deal_request.max_price_per_32_gib_per_month,
                                                               deposit_for_months=1)
    max_cost_per_month_str = utils.str_from_wei(max_cost_per_month, payment_token_decimals)

    total_max_cost = max_cost_per_month * deal_duration_months
    total_max_cost_str = utils.str_from_wei(total_max_cost, payment_token_decimals)

    # TODO LATER print account info (you now have ... at address ...)
    utils.confirm(f"\nProposing deal: {utils.json_pretty(deal_request)}\n\n"
                  f"This will cost you maximum of {max_cost_per_month_str} {payment_token_symbol} per month. "
                  f"This is a total of {total_max_cost_str} {payment_token_symbol} for {duration_months} months. "
                  f"Continue?", abort=True)

    tx_hash = PoRepMarket().propose_deal(deal_request, client_signer())
    click.echo(f"Created deal proposal from manifest {manifest_url}: {tx_hash}")


@click.command()
@click.argument("manifest_url")
@click.option("--price-per-tib-per-month", type=click.FloatRange(min=0, min_open=True), required=True,
              prompt="Enter maximum monthly price per 1 TiB in decimal format in given --payment-token tokens (e.g., 1.5 for 1.5 USDC)",
              help="Maximum monthly price per 1 TiB in decimal format in given --payment-token tokens. (e.g., 1.5 for 1.5 USDC).")
@click.option("--duration-months", type=click.IntRange(min=6), required=True,
              prompt="Enter deal duration in months (minimum 6 months)",
              help="Deal duration in months. Minimum supported is 6 months.")
@click.option("--payment-token", envvar="USDC_TOKEN", required=True,
              prompt="Enter address of the ERC20 token to pay with",
              help="Address of the ERC20 token to pay with.  [default: USDC_TOKEN env var]")
@click.option("--deal-type", type=click.Choice(PoRepMarketDealType.to_string_list(), case_sensitive=False), required=True,
              prompt="Enter type of the deal to propose",
              help="Type of the deal to propose.")
@click.option("--retrievability-bps", type=click.IntRange(0, 10000), required=True,
              prompt="Enter retrievability guarantee in bps (basis points, e.g. 7550 = 75.50%); 0 means \"don't care\"",
              help="Retrievability guarantee in bps (basis points, e.g. 7550 = 75.50%); 0 means \"don't care\".")
@click.option("--bandwidth-mbps", type=click.IntRange(0, 64000), required=True,
              prompt="Enter bandwidth guarantee in Mbps; 0 means \"don't care\"",
              help="Bandwidth guarantee in Mbps; 0 means \"don't care\".")
@click.option("--latency-ms", type=click.IntRange(min=0), required=True,
              prompt="Enter latency guarantee in milliseconds; 0 means \"don't care\"",
              help="Latency guarantee in milliseconds; 0 means \"don't care\".")
@click.option("--indexing-pct", type=click.IntRange(0, 100), required=True,
              prompt="Enter IPNI indexing guarantee in percentage; 0 means \"don't care\"",
              help="IPNI indexing guarantee in percentage; 0 means \"don't care\".")
def propose_deal(manifest_url: str,
                 retrievability_bps: int,
                 bandwidth_mbps: int,
                 price_per_tib_per_month: float,
                 duration_months: int,
                 latency_ms: int,
                 indexing_pct: int,
                 payment_token: str,
                 deal_type: str):
    """
    Interactively propose a deal from MANIFEST_URL with the specified parameters.

    \b
    1. Fetch and validate manifest from a given MANIFEST_URL,
    2. prepare and confirm deal proposal details,
    3. propose deal on-chain via PoRep Market contract.

    MANIFEST_URL - URL of the deal manifest file to download.
    """

    _propose_deal(manifest_url,
                  retrievability_bps,
                  bandwidth_mbps,
                  price_per_tib_per_month,
                  duration_months,
                  latency_ms,
                  indexing_pct,
                  EthAddress.from_any(payment_token),
                  PoRepMarketDealType.from_web3(deal_type))


@click.command(hidden=True)
@click.argument("manifest_url")
def propose_deal_mocked(manifest_url: str):
    retrievability_bps = 10
    bandwidth_mbps = 1
    price_per_tib_per_month = 1  # 1 USDC per TiB per month
    duration_months = 6
    latency_ms = 999
    indexing_pct = 1

    _propose_deal(manifest_url,
                  retrievability_bps,
                  bandwidth_mbps,
                  price_per_tib_per_month,
                  duration_months,
                  latency_ms,
                  indexing_pct,
                  USDCToken().address(),
                  PoRepMarketDealType.PUBLIC)
