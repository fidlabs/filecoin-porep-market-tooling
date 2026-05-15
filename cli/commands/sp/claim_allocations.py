from pathlib import Path

import click

from cli.commands.sp import deal_onboarding


@click.command(context_settings=dict(ignore_unknown_options=True, allow_extra_args=True))
@click.argument("software", type=click.Choice(["curio", "boost"], case_sensitive=False))
@click.argument("deal_id", type=click.IntRange(min=0))
@click.option("--cars-dir", type=click.Path(exists=True, file_okay=False), help="Directory containing .cid files, used for boost software.")
@click.pass_context
def claim_allocations(ctx, software: str, deal_id: int, cars_dir: str | None = None):
    """
    \b
    Interactively claim DDO allocations for a deal using the specified software.

    \b
    Runs `curio market ddo --actor <deal.provider_id> <client_contract_filecoin_address> <allocation_id>` for curio or
         `boostd import-direct --allocation-id <allocation_id> <cid> <car_file>` for boost, for each allocation in the deal.

    \b
    Unknown [OPTIONS] are passed directly to SOFTWARE, allowing for flexible configuration.
    For available options see:
    `curio --help` and https://docs.curiostorage.org/curio-market/storage-market#start-a-ddo-deal,
    `boostd --help` and https://boost.filecoin.io/experimental-features/direct-deals.

    \b
    SOFTWARE - The software to use for claiming allocations.
    DEAL_ID - The id of the deal to claim allocations for.
    """

    deal_onboarding.claim_deal_allocations(
        software,
        deal_id,
        cars_dir=Path(cars_dir).resolve() if cars_dir else None,
        extra_args=ctx.args,
        interactive=True,
    )
