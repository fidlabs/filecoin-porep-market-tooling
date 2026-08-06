import click
import humanfriendly

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.admin._admin import admin_address, admin_signer
from cli.services.contracts.erc20_contract import ERC20Contract
from cli.services.contracts.porep_market import (
    PoRepMarket,
    PoRepMarketDealRequest,
    PoRepMarketDealState,
    PoRepMarketSLIThresholds,
)
from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper
from cli.services.contracts.sp_registry import SPRegistry
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import EthAddress, Web3Service


@click.command()
@click.argument("offer_id", type=click.IntRange(min=1))
@click.argument("manifest_url")
@click.option("--retrievability-bps", type=click.IntRange(0, 10000), required=True,
              help="Retrievability guarantee in bps (basis points, e.g. 7550 = 75.50%); 0 means \"don't care\".")
@click.option("--bandwidth-mbps", type=click.IntRange(0, 64000), required=True,
              help="Bandwidth guarantee in Mbps. Capped at ~64 Gbps.")
# TODO LATER make this price-per-tib-per-month?
@click.option("--price-per-sector-per-month", help="Maximum monthly price per 32 GiB sector in payment token smallest units (wei-equivalent).",
              type=click.IntRange(min=0), required=True)
@click.option("--duration-months", type=click.IntRange(min=6), required=True,
              help="Deal duration in months. Minimum supported is 6 months.")
@click.option("--latency-ms", type=click.IntRange(min=0), required=True,
              help="Latency guarantee in milliseconds.")
@click.option("--indexing-pct", type=click.IntRange(0, 100), default=0, show_default=True,
              help="IPNI indexing guarantee in percentage; 0 means \"don't care\".")
@click.option("--payment-token", envvar="USDC_TOKEN", required=True,
              help="Address of the ERC20 token to pay with.  [default: USDC_TOKEN env var]")
def propose_deal_with_specific_offer(offer_id: int,
                                     manifest_url: str,
                                     retrievability_bps: int,
                                     bandwidth_mbps: int,
                                     price_per_sector_per_month: int,
                                     duration_months: int,
                                     latency_ms: int,
                                     indexing_pct: int,
                                     payment_token: str):
    """
    Interactively propose a deal from MANIFEST_URL against a specific OFFER_ID,
    bypassing automatic Storage Provider matching.

    \b
    1. Fetch and validate manifest from a given MANIFEST_URL,
    2. fetch and display the reserved offer,
    3. prepare and confirm deal proposal details,
    4. propose deal on-chain via PoRep Market contract, reserving OFFER_ID.

    Note: the admin account becomes the client of the resulting deal.

    \b
    OFFER_ID - The ID of the Storage Provider offer to reserve for the deal.
    MANIFEST_URL - URL of the deal manifest file to download.
    """

    SelfUpdateService.check_and_prompt(manual=False)

    MBPS_TO_BYTES_PER_SECOND = 125_000  # 1 Mbps = 10^6 bits/s / 8 = 125 000 bytes/s
    payment_token_address = EthAddress(payment_token)

    offer = SPRegistry().get_offer_view(offer_id)
    utils.confirm(f"\nReserving offer for deal: {utils.json_pretty(offer)}\n\n"
                  "This bypasses automatic Storage Provider matching. Continue?", abort=True)

    manifest, raw_manifest = commands_utils.fetch_manifest(manifest_url)
    pieces = manifest[0]["pieces"]
    pieces_size_bytes = sum(piece.get("pieceSize", 0) for piece in pieces)

    if pieces_size_bytes <= 0:
        raise ValueError("Invalid deal size")

    click.echo(f"\nFound {len(pieces)} pieces with total pieceSize "
               f"{humanfriendly.format_size(pieces_size_bytes)} = {humanfriendly.format_size(pieces_size_bytes, binary=True)} = "
               f"{utils.bytes_to_sectors(pieces_size_bytes, PoRepMarket().get_sector_size_bytes())} sectors "
               f"(including dag piece)")

    # noinspection PyArgumentList
    deal_request = PoRepMarketDealRequest(
        manifest_hash=commands_utils.hash_manifest(raw_manifest),
        requested_size_bytes=pieces_size_bytes,
        max_price_per_32_gib_per_month=price_per_sector_per_month,
        manifest_location=manifest_url,
        payment_token_address=payment_token_address,
        duration_days=duration_months * 30,  # PoRep Market smart contracts assumes month == 30 days
        required_slis=PoRepMarketSLIThresholds(
            retrievability_bps=retrievability_bps,
            bandwidth_bytes_per_second=bandwidth_mbps * MBPS_TO_BYTES_PER_SECOND,
            latency_ms=latency_ms,
            indexing_pct=indexing_pct,
        )
    )

    Web3Service().wait_for_pending_transactions(admin_address())
    existing_deals = commands_utils.get_client_deals(admin_address())

    # warn if any of the admin's existing deals looks similar to the new deal proposal
    for existing_deal in existing_deals:
        is_active = existing_deal.state in [PoRepMarketDealState.PROPOSED, PoRepMarketDealState.ACCEPTED, PoRepMarketDealState.ACTIVE]
        existing_deal_view = PoRepMarketViewHelper().get_deal_view(existing_deal.deal_id)

        if deal_request.requested_size_bytes == existing_deal_view.terms.requested_size_bytes:
            utils.confirm(f"\nWarning: Admin deal with the same deal size "
                          f"already exists in PoRep Market: {utils.json_pretty(existing_deal)} "
                          "Continue?", default=not is_active, abort=True)

        if deal_request.manifest_location == existing_deal_view.data.manifest_location:
            utils.confirm(
                f"\nWarning: Admin deal with the same manifest location "
                f"already exists in PoRep Market: {utils.json_pretty(existing_deal)} "
                "Continue?", default=not is_active, abort=True)

    payment_token_contract = ERC20Contract(payment_token_address)
    token_symbol = payment_token_contract.symbol()
    deal_duration_months = deal_request.duration_days // 30  # PoRep Market smart contracts assumes month == 30 days

    max_cost_per_month = commands_utils.calculate_deposit_amount(deal_request.requested_size_bytes,
                                                                 deal_request.max_price_per_32_gib_per_month,
                                                                 deposit_for_months=1)
    max_cost_per_month_str = utils.str_from_wei(max_cost_per_month, payment_token_contract.decimals())

    total_max_cost = max_cost_per_month * deal_duration_months
    total_max_cost_str = utils.str_from_wei(total_max_cost, payment_token_contract.decimals())

    # TODO LATER print account info (you now have ... at address ...)
    utils.confirm(f"\nProposing deal against offer {offer_id}: {utils.json_pretty(deal_request)}\n\n"
                  f"This will cost the admin account a maximum of {max_cost_per_month_str} {token_symbol} per month. "
                  f"This is a total of {total_max_cost_str} {token_symbol} for {duration_months} months. "
                  f"The admin account becomes the client of the resulting deal. Continue?", abort=True)

    tx_hash = PoRepMarket().propose_deal_with_specific_offer(offer_id, deal_request, admin_signer())
    click.echo(f"Created deal proposal from manifest {manifest_url} against offer {offer_id}: {tx_hash}")
