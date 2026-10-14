import sys
import time
from decimal import Decimal

import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.client import _repair
from cli.commands.client._client import client_address, client_signer
from cli.commands.client.init_deal import init_deal
from cli.commands.client.make_allocations import make_allocations
from cli.commands.repair_utils import RetrievalSource, ensure_usdfc, find_healthy_source, resolve_repair_payee
from cli.services.contracts.erc20_contract import ERC20Contract
from cli.services.contracts.porep_market import PoRepMarket, PoRepMarketDealState
from cli.services.contracts.porep_market_view_helper import PoRepMarketDealView, PoRepMarketViewHelper
from cli.services.self_update import SelfUpdateService

EPOCHS_PER_MONTH = 30 * 2880  # PoRep Market months are 30 days of 2880 epochs
ACCEPTANCE_POLL_SECONDS = 30
PENDING_DEAL_STATES = (PoRepMarketDealState.PROPOSED, PoRepMarketDealState.ACCEPTED)


@click.command()
@click.argument("deal_id", type=click.IntRange(min=1))
@click.option("--source-url",
              help="Override: base URL of the healthy SP's piece server / sp-proxy (e.g. https://sp.example.com:8787).  "
                   "[default: auto-detected from other providers' deals for the same dataset]")
@click.option("--price-per-tib-per-month", type=click.FloatRange(min=0, min_open=True),
              help="Maximum monthly price per 1 TiB for the new deal, in the deal's payment token.  [default: DEAL_ID's price]")
@click.option("--duration-months", type=click.IntRange(min=6),
              help="Duration of the new deal in months.  [default: DEAL_ID's duration]")
@click.option("--wait-minutes", type=click.IntRange(min=0), default=10, show_default=True,
              help="How long to wait for the matched SP to accept a newly proposed deal before stopping; re-run to resume.")
@click.option("--repair-deal", type=click.IntRange(min=1),
              help="Continue this deal as the repair of DEAL_ID instead of looking for one marked as its repair, e.g. a repair "
                   "deal proposed before repair deals were marked; asks for confirmation unless the deal is marked for DEAL_ID.")
@click.option("--allow-unverified-history", is_flag=True, default=False,
              help="Deposit even if earlier deposits to the payee can't be checked (RPC log limits); only after checking them yourself.  "
                   "[default: false]")
@click.option("--allow-repeat-deposit", is_flag=True, default=False,
              help="Deposit even though earlier deposits to the payee already cover the cost (e.g. they were for another deal with "
                   "the same SP).  [default: false]")
@click.pass_context
def repair(ctx,
           deal_id: int,
           source_url: str | None = None,
           price_per_tib_per_month: float | None = None,
           duration_months: int | None = None,
           wait_minutes: int = 10,
           repair_deal: int | None = None,
           allow_unverified_history: bool = False,
           allow_repeat_deposit: bool = False):
    """
    \b
    FCSS repair: re-onboard DEAL_ID's dataset with a new SP, fetching it from a healthy SP. Resumable: re-run the
    same command after any interruption and it continues from the state on-chain.

    \b
    1. Find the repair deal of an earlier run: a deal marked on-chain as the repair of DEAL_ID (its manifest URL
       ends in #fcss-repair-of=DEAL_ID) that is still PROPOSED or ACCEPTED, or ACTIVE (the repair is done); if
       there is none, find a healthy SP and its exact retrieval quote, then propose a marked deal with DEAL_ID's
       terms (the market matches the SP as for any other deal),
    2. wait up to --wait-minutes for the SP to accept it,
    3. deposit the one-off retrieval cost into the FileCoinPay account of the new SP's payee (as
       `client pay-repair-retrieval`; skipped when already deposited),
    4. initialize the deal and make its DDO allocations (as `client init-deal` and `client make-allocations`).

    DEAL_ID - The deal being repaired (the SP that lost or no longer serves the data).
    """

    SelfUpdateService.check_and_prompt(manual=False)

    old_deal = PoRepMarketViewHelper().get_deal_view(deal_id)

    if old_deal.deal.client_address != client_address():
        raise click.ClickException(f"Deal ID {deal_id} client address {old_deal.deal.client_address} "
                                   f"does not match with connected client address {client_address()}.")

    _repair.ensure_repairable(old_deal)
    ensure_usdfc(old_deal.payment.payment_token, f"Deal ID {deal_id}")

    new_deal = _given_repair_deal(old_deal, repair_deal) if repair_deal else _find_repair_deal(old_deal)
    source = None

    if new_deal is not None and new_deal.deal.state == PoRepMarketDealState.ACTIVE:
        click.echo(f"\nRepair of deal ID {deal_id} is done: repair deal ID {new_deal.deal.deal_id} (provider "
                   f"{new_deal.deal.provider_id}) is ACTIVE.")
        return

    if new_deal is None:
        new_deal_id, source = _propose_repair_deal(old_deal, source_url, price_per_tib_per_month, duration_months)

        if new_deal_id is None:
            click.echo("\nNo deal created.")
            return

        new_deal = PoRepMarketViewHelper().get_deal_view(new_deal_id)

    resume_command = f"`{sys.argv[0]} client repair {deal_id}" + (f" --source-url {source_url}" if source_url else "") + \
                     (f" --repair-deal {repair_deal}" if repair_deal else "") + "`"

    if new_deal.deal.state == PoRepMarketDealState.PROPOSED:
        new_deal = _wait_for_acceptance(new_deal.deal.deal_id, wait_minutes)

    if new_deal.deal.state == PoRepMarketDealState.PROPOSED:
        click.echo(f"\nRepair deal ID {new_deal.deal.deal_id} is not accepted yet. Re-run {resume_command} once it is to continue.")
        return

    if new_deal.deal.state != PoRepMarketDealState.ACCEPTED:
        raise click.ClickException(f"Repair deal ID {new_deal.deal.deal_id} is in state {new_deal.deal.state}; re-run "
                                   f"{resume_command} to propose a new one.")

    click.echo(f"\nRepair deal ID {new_deal.deal.deal_id} accepted by provider {new_deal.deal.provider_id}.")
    _repair.pay_repair_retrieval(new_deal.deal.deal_id, deal_id, source_url, source=source,
                                 allow_unverified_history=allow_unverified_history, allow_repeat_deposit=allow_repeat_deposit,
                                 covered_is_done=True)

    ctx.invoke(init_deal, deal_id=new_deal.deal.deal_id)
    ctx.invoke(make_allocations, deal_id=new_deal.deal.deal_id)

    click.echo(f"\nRepair of deal ID {deal_id} set up as deal ID {new_deal.deal.deal_id}; the new SP now downloads the data "
               f"with `sp onboard-data {new_deal.deal.deal_id}`.")


# The CLI keeps no local state, so an earlier run's repair deal is found on-chain, by its repair marker (see _repair.REPAIR_MARKER):
# the dataset's other original copy is newer than DEAL_ID as often as not, so recency and dataset alone can't identify it.
# A marked ACTIVE deal means the repair is done. Unmarked pending deals for the dataset are never picked: they are listed, and
# proposing another deal needs a confirmation (a repair proposed before repair deals were marked resumes with --repair-deal).
def _find_repair_deal(old_deal: PoRepMarketDealView) -> PoRepMarketDealView | None:
    marked = []
    unmarked_pending = []

    for deal in commands_utils.get_client_deals(client_address()):
        if deal.deal_id == old_deal.deal.deal_id or deal.provider_id == old_deal.deal.provider_id:
            continue

        if deal.state not in PENDING_DEAL_STATES + (PoRepMarketDealState.ACTIVE,):
            continue

        view = PoRepMarketViewHelper().get_deal_view(deal.deal_id)

        if bytes(view.data.manifest_hash) != bytes(old_deal.data.manifest_hash):
            continue

        marker = _repair.get_repair_marker(view.data.manifest_location)

        if marker == old_deal.deal.deal_id:
            marked.append(view)
        elif marker is None and deal.state in PENDING_DEAL_STATES and deal.proposed_at_epoch > old_deal.deal.proposed_at_epoch:
            unmarked_pending.append(view)

    active = [view for view in marked if view.deal.state == PoRepMarketDealState.ACTIVE]
    pending = [view for view in marked if view.deal.state in PENDING_DEAL_STATES]

    if active:
        return max(active, key=lambda view: view.deal.deal_id)

    if pending:
        new_deal = max(pending, key=lambda view: view.deal.deal_id)

        if len(pending) > 1:
            click.echo(f"Several pending repair deals of deal ID {old_deal.deal.deal_id} found "
                       f"({', '.join(str(view.deal.deal_id) for view in pending)}); continuing with the latest.")

        click.echo(f"Continuing repair deal ID {new_deal.deal.deal_id} ({new_deal.deal.state}, provider {new_deal.deal.provider_id}).")
        return new_deal

    if unmarked_pending:
        deals_str = ", ".join(f"{view.deal.deal_id} ({view.deal.state}, provider {view.deal.provider_id})" for view in unmarked_pending)
        utils.confirm(f"\nDeal(s) {deals_str} for the same dataset are pending but not marked as the repair of deal ID "
                      f"{old_deal.deal.deal_id}: they may be the dataset's other original copy, or a repair proposed before repair "
                      f"deals were marked. To continue one of them as this repair, re-run with --repair-deal <deal-id>.\n"
                      f"Propose a new repair deal anyway?", default=False, abort=True)

    return None


# --repair-deal: the client names the repair deal. A deal marked as the repair of another deal is refused; an unmarked one
# (proposed before repair deals were marked) is only taken after a confirmation that defaults to No, since nothing on-chain
# links it to DEAL_ID and its SP's payee receives the non-refundable retrieval deposit.
def _given_repair_deal(old_deal: PoRepMarketDealView, repair_deal_id: int) -> PoRepMarketDealView:
    view = PoRepMarketViewHelper().get_deal_view(repair_deal_id)
    old_deal_id = old_deal.deal.deal_id

    if view.deal.client_address != client_address():
        raise click.ClickException(f"Deal ID {repair_deal_id} client address {view.deal.client_address} "
                                   f"does not match with connected client address {client_address()}.")

    if repair_deal_id == old_deal_id or view.deal.provider_id == old_deal.deal.provider_id:
        raise click.ClickException(f"Deal ID {repair_deal_id} is with deal ID {old_deal_id}'s own provider "
                                   f"{old_deal.deal.provider_id}, so it can't repair it.")

    if bytes(view.data.manifest_hash) != bytes(old_deal.data.manifest_hash):
        raise click.ClickException(f"Deal ID {repair_deal_id} stores another dataset than deal ID {old_deal_id} (manifest hash differs).")

    if view.deal.state not in PENDING_DEAL_STATES + (PoRepMarketDealState.ACTIVE,):
        raise click.ClickException(f"Deal ID {repair_deal_id} is in state {view.deal.state}; run without --repair-deal to propose a new "
                                   f"repair deal.")

    marker = _repair.get_repair_marker(view.data.manifest_location)

    if marker == old_deal_id:
        return view

    if marker is not None:
        raise click.ClickException(f"Deal ID {repair_deal_id} is marked as the repair of deal ID {marker}, not {old_deal_id}.")

    utils.confirm(f"\nDeal ID {repair_deal_id} ({view.deal.state}, provider {view.deal.provider_id}) has no repair marker, so nothing "
                  f"on-chain links it to deal ID {old_deal_id}. Continue it as the repair of deal ID {old_deal_id}? Its SP's payee "
                  f"{resolve_repair_payee(view)} receives the non-refundable retrieval deposit.", default=False, abort=True)
    return view


def _propose_repair_deal(old_deal: PoRepMarketDealView,
                         source_url: str | None,
                         price_per_tib_per_month: float | None,
                         duration_months: int | None) -> tuple[int | None, RetrievalSource]:
    #
    manifest_url = _repair.with_repair_marker(old_deal.data.manifest_location, old_deal.deal.deal_id)
    manifest, _ = commands_utils.fetch_manifest(old_deal.data.manifest_location, show_manifest=False, quiet=True, retries=10)

    # show the repair cost before the proposal is confirmed
    source = find_healthy_source(old_deal.data.manifest_hash, manifest[0]["pieces"], {old_deal.deal.provider_id}, source_url)
    click.echo(f"\nOne-off repair retrieval cost quoted by {source.base_url}, paid once the matched SP accepts the deal: "
               f"{source.quote.total} USDFC for {source.quote.paid_pieces} paid piece(s)")

    # propose_deal takes whole percent and Mbps: round up, so the new deal never asks for less than the old one
    slis = old_deal.required_slis
    deal_id = commands_utils.propose_deal(client_signer(),
                                          manifest_url,
                                          -(-slis.retrievability_bps // 100),
                                          -(-slis.bandwidth_bytes_per_second // utils.Mbps_to_Bps(1)),
                                          price_per_tib_per_month or _old_price_per_tib(old_deal),
                                          duration_months or _old_duration_months(old_deal),
                                          slis.latency_ms,
                                          slis.indexing_pct,
                                          old_deal.payment.payment_token,
                                          old_deal.deal.deal_type)
    return deal_id, source


# propose_deal takes a decimal price per TiB; only reuse the old price if it converts back to exactly the same per-sector price
def _old_price_per_tib(old_deal: PoRepMarketDealView) -> float:
    decimals = ERC20Contract(old_deal.payment.payment_token).decimals()
    sector_size_bytes = PoRepMarket().get_sector_size_bytes()
    price_per_sector = old_deal.payment.price_per_32_gib_per_month
    price = float(Decimal(price_per_sector * (1024 ** 4 // sector_size_bytes)).scaleb(-decimals))

    try:
        if utils.price_per_TiB_tokens_to_per_sector_wei(price, decimals, sector_size_bytes) == price_per_sector:
            return price
    except ValueError:
        pass

    raise click.UsageError(f"Deal ID {old_deal.deal.deal_id} price can't be reused exactly; set --price-per-tib-per-month.")


def _old_duration_months(old_deal: PoRepMarketDealView) -> int:
    months, remainder = divmod(old_deal.terms.duration_epochs, EPOCHS_PER_MONTH)

    if remainder or months < 6:
        raise click.UsageError(f"Deal ID {old_deal.deal.deal_id} duration of {old_deal.terms.duration_epochs} epochs is not a whole "
                               f"number of months (6 or more); set --duration-months.")

    return months


def _wait_for_acceptance(deal_id: int, wait_minutes: int) -> PoRepMarketDealView:
    deadline = time.monotonic() + wait_minutes * 60
    deal = PoRepMarketViewHelper().get_deal_view(deal_id)

    if deal.deal.state == PoRepMarketDealState.PROPOSED and wait_minutes:
        click.echo(f"\nWaiting up to {wait_minutes} minute(s) for provider {deal.deal.provider_id} to accept deal ID {deal_id}...")

    while deal.deal.state == PoRepMarketDealState.PROPOSED and time.monotonic() < deadline:
        time.sleep(ACCEPTANCE_POLL_SECONDS)
        deal = PoRepMarketViewHelper().get_deal_view(deal_id)

    return deal
