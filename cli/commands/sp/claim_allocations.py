import subprocess
from pathlib import Path

import click

from cli import utils
from cli.commands.sp import _utils as sp_utils
from cli.services.contracts.client_contract import ClientContract
from cli.services.contracts.porep_market import PoRepMarket, PoRepMarketDealProposal
from cli.services.web3_service import FilAddress


def _get_curio_path() -> str:
    curio_path = utils.get_env_required("CURIO_PATH", default="curio")

    if curio_path != "curio":
        curio_path = Path(curio_path).resolve()

    # noinspection PyBroadException
    try:
        subprocess.run([curio_path, "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    # pylint: disable=broad-exception-caught
    except Exception as e:
        click.echo("curio not found. Please install curio to use this command.\n"
                   "See https://docs.curiostorage.org/ for more information.\n"
                   "Set the CURIO_PATH environment variable if curio is installed but not in PATH.\n")

        raise click.ClickException(f"{curio_path} not found:\n{e}") from e

    return str(curio_path)


def _build_allocation_command_curio(curio_path: str,
                                    client_contract_filecoin_address: FilAddress,
                                    allocation_id: int,
                                    deal: PoRepMarketDealProposal) -> list[str]:
    return [
        curio_path,
        "market",
        "ddo",
        "--actor",
        deal.provider_id,
        client_contract_filecoin_address,
        str(allocation_id),
    ]


@click.command(context_settings=dict(ignore_unknown_options=True, allow_extra_args=True))
@click.argument("software", type=click.Choice(["curio"], case_sensitive=False))
@click.argument("deal_id", type=click.IntRange(min=0))
@click.pass_context
def claim_allocations(ctx, software: str, deal_id: int):
    """
    \b
    Interactively claim DDO allocations for a deal using the specified software.

    \b
    Unknown [OPTIONS] are passed directly to SOFTWARE, allowing for flexible configuration.
    For available options see:
    curio --help and https://docs.curiostorage.org/.

    \b
    SOFTWARE - The software to use for claiming allocations.
    DEAL_ID - The id of the deal to claim allocations for.
    """

    if software.lower() == "curio":
        curio_path = _get_curio_path()
        client_contract_filecoin_address = ClientContract().address().to_filecoin_address()

        def build_allocation_command(allocation_id: int, deal: PoRepMarketDealProposal) -> list[str]:
            return _build_allocation_command_curio(curio_path, client_contract_filecoin_address, allocation_id, deal)
    else:
        raise click.ClickException(f"Unsupported software: {software}")

    deal = PoRepMarket().get_deal_proposal(deal_id)
    deal_allocations = sp_utils.get_deal_allocations(deal)

    click.echo(f"Found {len(deal_allocations)} allocations for deal id {deal_id}: {utils.json_pretty(deal_allocations)}\n")

    for allocation in deal_allocations:
        allocation_id = allocation["allocationId"]
        command = build_allocation_command(allocation_id, deal) + ctx.args

        try:
            if not click.confirm(f"\nRunning command:\n  {' '.join(command)}\nContinue?"):
                click.echo("Skipped this allocation")
                continue

            click.echo()
            subprocess.run(command, check=True)
        except subprocess.CalledProcessError as e:
            click.echo(f"\nCommand failed with exit code {e.returncode}")
