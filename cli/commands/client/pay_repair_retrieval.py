import click

from cli.commands.client import _repair
from cli.services.self_update import SelfUpdateService


@click.command()
@click.argument("deal_id", type=click.IntRange(min=1))
@click.option("--repair-of", type=click.IntRange(min=1),
              help="Deal ID being repaired; verifies DEAL_ID stores the same dataset (same manifest hash) "
                   "and excludes its SP as a retrieval source.")
@click.option("--source-url",
              help="Override: base URL of the healthy SP's piece server / sp-proxy (e.g. https://sp.example.com:8787).  "
                   "[default: auto-detected from other providers' deals for the same dataset]")
@click.option("--allow-unverified-history", is_flag=True, default=False,
              help="Deposit even if earlier deposits to the payee can't be checked (RPC log limits); only after checking them yourself.  "
                   "[default: false]")
@click.option("--allow-repeat-deposit", is_flag=True, default=False,
              help="Deposit even though earlier deposits to the payee already cover the cost (e.g. they were for another deal with "
                   "the same SP).  [default: false]")
def pay_repair_retrieval(deal_id: int,
                         repair_of: int | None = None,
                         source_url: str | None = None,
                         allow_unverified_history: bool = False,
                         allow_repeat_deposit: bool = False):
    """
    One-off payment of a repair retrieval for a new SP.

    \b
    1. Find the source of the data: --source-url, or a healthy SP found automatically (another provider's
       ACTIVE, PUBLIC deal with the same manifest hash and claims on-chain, whose advertised piece endpoint
       serves the data),
    2. get the source's exact quote for every piece with `retrieval-client fetch --dry-run` (nothing to pay if free),
    3. check earlier deposits from this client to the payee since DEAL_ID was proposed: refuse if they can't be
       checked or already cover the cost (see the --allow-* flags), deposit only the shortfall if they cover part,
    4. deposit into the FileCoinPay account of DEAL_ID's SP payee, so the new SP can pay the healthy SP without
       fronting the cost and without any client keys or off-chain coordination.

    DEAL_ID must be ACCEPTED or ACTIVE: the deposit can only be returned by the SP, so it waits for the SP to
    accept the deal. This is separate from and in addition to the regular deal payment (`client init-deal`).
    The same step runs as part of `client repair`.

    DEAL_ID - The new (repair) deal ID.
    """

    SelfUpdateService.check_and_prompt(manual=False)

    _repair.pay_repair_retrieval(deal_id, repair_of, source_url,
                                 allow_unverified_history=allow_unverified_history, allow_repeat_deposit=allow_repeat_deposit)
