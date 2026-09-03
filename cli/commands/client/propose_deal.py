import click

from cli.commands import utils as commands_utils
from cli.commands.client._client import client_signer
from cli.services.contracts.porep_market import PoRepMarketDealType
from cli.services.contracts.usdc_token import USDCToken
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import EthAddress


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
@click.option("--deal-type", required=True,
              type=click.Choice(PoRepMarketDealType.to_selectable_string_list(), case_sensitive=False),
              prompt="Enter type of the deal to propose",
              help="Type of the deal to propose.")
@click.option("--retrievability-pct", type=click.IntRange(0, 100), required=True,
              prompt="Enter retrievability guarantee in percentage; 0 means \"don't care\"",
              help="Retrievability guarantee in percentage; 0 means \"don't care\".")
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
                 retrievability_pct: int,
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

    MANIFEST_URL - URL of the deal manifest file to use.
    """

    SelfUpdateService.check_and_prompt(manual=False)

    commands_utils.propose_deal(client_signer(),
                                manifest_url,
                                retrievability_pct,
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
    retrievability_pct = 1
    bandwidth_mbps = 1
    price_per_tib_per_month = 1  # 1 USDC per TiB per month
    duration_months = 6
    latency_ms = 999
    indexing_pct = 1

    commands_utils.propose_deal(client_signer(),
                                manifest_url,
                                retrievability_pct,
                                bandwidth_mbps,
                                price_per_tib_per_month,
                                duration_months,
                                latency_ms,
                                indexing_pct,
                                USDCToken().address(),
                                PoRepMarketDealType.PUBLIC)
