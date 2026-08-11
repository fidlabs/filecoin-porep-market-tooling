import click
import humanfriendly

from cli import utils
from cli.commands.sp._sp import sp_address, sp_signer
from cli.services.contracts.erc20_contract import ERC20Contract
from cli.services.contracts.porep_market import PoRepMarketSLIThresholds, PoRepMarket
from cli.services.contracts.sp_registry import SPRegistryOfferInput, SPRegistry, SPRegistryOfferTerms, SPRegistryOfferPaymentInput
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import Web3Service, EthAddress


@click.command()
@click.argument("provider_id")
@click.option("--min-size", required=True,
              prompt="Enter minimum size of the deal in human readable size format (e.g., '1 TiB', 500GiB)",
              help="Minimum size of the deal you want to accept in human readable size format (e.g., '1 TiB', 500GiB).")
@click.option("--max-size", required=True,
              prompt="Enter maximum size of the deal in human readable size format (e.g., '1 TiB', 500GiB)",
              help="Maximum size of the deal you want to accept in human readable size format (e.g., '1 TiB', 500GiB).")
@click.option("--min-duration-months", type=click.IntRange(min=6), required=True,
              prompt="Enter minimum duration of the deal in months (minimum supported is 6 months)",
              help="Minimum duration of the deal you want to accept in months. Minimum supported is 6 months.")
@click.option("--max-duration-months", type=click.IntRange(min=6), required=True,
              prompt="Enter maximum duration of the deal in months",
              help="Maximum duration of the deal you want to accept in months.")
@click.option("--payment-token", envvar="USDC_TOKEN", required=True,
              prompt="Enter address of the ERC20 token to be paid with",
              help="Address of the ERC20 token to be paid with.  [default: USDC_TOKEN env var]")
@click.option("--min-price-per-tib-per-month", type=click.FloatRange(min=0, min_open=True), required=True,
              prompt="Enter minimum monthly price per 1 TiB in decimal format in given --payment-token tokens (e.g., 1.5 for 1.5 USDC)",
              help="Minimum monthly price per 1 TiB in decimal format in given --payment-token tokens. (e.g., 1.5 for 1.5 USDC).")
@click.option("--retrievability-bps", type=click.IntRange(0, 10000), required=True,
              prompt="Enter retrievability guarantee in bps (basis points, e.g. 7550 = 75.50%)",
              help="Retrievability guarantee in bps (basis points, e.g. 7550 = 75.50%).")
@click.option("--bandwidth-mbps", type=click.IntRange(0, 64000), required=True,
              prompt="Enter bandwidth guarantee in Mbps",
              help="Bandwidth guarantee in Mbps.")
@click.option("--latency-ms", type=click.IntRange(min=0), required=True,
              prompt="Enter latency guarantee in milliseconds",
              help="Latency guarantee in milliseconds.")
@click.option("--indexing-pct", type=click.IntRange(0, 100), required=True,
              prompt="Enter IPNI indexing guarantee in percentage",
              help="IPNI indexing guarantee in percentage.")
def register_offer(provider_id: str,
                   min_size: str,
                   max_size: str,
                   min_duration_months: int,
                   max_duration_months: int,
                   payment_token: str,
                   min_price_per_tib_per_month: float,
                   retrievability_bps: int,
                   bandwidth_mbps: int,
                   latency_ms: int,
                   indexing_pct: int):
    """
    Interactively register a new PoRep Market offer on-chain via SPRegistry contract.

    \b
    PROVIDER_ID - Provider ID to register the offer for.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(sp_address())

    EPOCHS_IN_MONTH = PoRepMarket().get_epochs_in_month()

    _payment_token = EthAddress.from_any(payment_token)
    price_per_32_gib_per_month_wei = utils.price_per_TiB_tokens_to_per_sector_wei(
        min_price_per_tib_per_month,
        ERC20Contract(_payment_token).decimals(),
        PoRepMarket().get_sector_size_bytes()
    )

    # noinspection PyArgumentList
    offer = SPRegistryOfferInput(provider_id=provider_id,
                                 terms=SPRegistryOfferTerms(
                                     min_size_bytes=humanfriendly.parse_size(min_size),
                                     max_size_bytes=humanfriendly.parse_size(max_size),
                                     min_duration_epochs=utils.months_to_epochs(min_duration_months, EPOCHS_IN_MONTH),
                                     max_duration_epochs=utils.months_to_epochs(max_duration_months, EPOCHS_IN_MONTH)
                                 ),
                                 slis=PoRepMarketSLIThresholds(
                                     retrievability_bps=retrievability_bps,
                                     bandwidth_bytes_per_second=utils.Mbps_to_bps(bandwidth_mbps),
                                     latency_ms=latency_ms,
                                     indexing_pct=indexing_pct
                                 ),
                                 payments=[
                                     SPRegistryOfferPaymentInput(
                                         token=_payment_token,
                                         active=True,
                                         price_per_32_gib_per_month=price_per_32_gib_per_month_wei
                                     )
                                 ])

    utils.confirm(f"Registering a new PoRep Market offer for provider {offer.provider_id} with parameters: {offer}", abort=True)

    tx_hash = SPRegistry().create_offer(offer, sp_signer())
    click.echo(f"Offer for provider {offer.provider_id} registered: {tx_hash}")


@click.command()
@click.argument("offer_id", type=click.IntRange(min=1))
@click.option("--min-size", type=click.IntRange(min=0), required=True,
              prompt="Enter minimum size of the deal in human readable size format (e.g., '1 TiB', 500GiB)",
              help="Minimum size of the deal you want to accept in human readable size format (e.g., '1 TiB', 500GiB).")
@click.option("--max-size", type=click.IntRange(min=0), required=True,
              prompt="Enter maximum size of the deal in human readable size format (e.g., '1 TiB', 500GiB)",
              help="Maximum size of the deal you want to accept in human readable size format (e.g., '1 TiB', 500GiB).")
@click.option("--min-duration-months", type=click.IntRange(min=6), required=True,
              prompt="Enter minimum duration of the deal in months",
              help="Minimum duration of the deal you want to accept in months. Minimum supported is 6 months.")
@click.option("--max-duration-months", type=click.IntRange(min=6), required=True,
              prompt="Enter maximum duration of the deal in months",
              help="Maximum duration of the deal you want to accept in months.")
@click.option("--payment-token", envvar="USDC_TOKEN", required=True,
              prompt="Enter address of the ERC20 token to be paid with",
              help="Address of the ERC20 token to be paid with.  [default: USDC_TOKEN env var]")
@click.option("--min-price-per-tib-per-month", type=click.FloatRange(min=0, min_open=True), required=True,
              prompt="Enter minimum monthly price per 1 TiB in decimal format in given --payment-token tokens (e.g., 1.5 for 1.5 USDC)",
              help="Minimum monthly price per 1 TiB in decimal format in given --payment-token tokens. (e.g., 1.5 for 1.5 USDC).")
@click.option("--retrievability-bps", type=click.IntRange(0, 10000), required=True,
              prompt="Enter retrievability guarantee in bps (basis points, e.g. 7550 = 75.50%)",
              help="Retrievability guarantee in bps (basis points, e.g. 7550 = 75.50%).")
@click.option("--bandwidth-mbps", type=click.IntRange(0, 64000), required=True,
              prompt="Enter bandwidth guarantee in Mbps",
              help="Bandwidth guarantee in Mbps.")
@click.option("--latency-ms", type=click.IntRange(min=0), required=True,
              prompt="Enter latency guarantee in milliseconds",
              help="Latency guarantee in milliseconds.")
@click.option("--indexing-pct", type=click.IntRange(0, 100), required=True,
              prompt="Enter IPNI indexing guarantee in percentage",
              help="IPNI indexing guarantee in percentage.")
def update_offer(offer_id: int):
    """
    Interactively update an existing PoRep Market offer on-chain via SPRegistry contract.

    OFFER_ID - Offer ID to update.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(sp_address())

    SPRegistryOfferInput
    click.echo("This command is not yet implemented.")
