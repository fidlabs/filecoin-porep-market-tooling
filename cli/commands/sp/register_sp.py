import click

from cli.commands import utils as commands_utils
from cli.commands.sp._sp import sp_address, sp_signer
from cli.services.contracts.sp_registry import SPRegistryProviderInput, SPRegistry
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import Web3Service, ActorId, EthAddress


@click.command()
@click.argument("provider_id")
@click.option("--organization",
              help="Organization that runs the SP.  [default: SP_ORGANIZATION env var]")
@click.option("--available-bytes",
              type=click.IntRange(min=0), help="Total SP capacity available for deals.")
@click.option("--payee-address",
              help="Address receiving SP payments for deals.")
def register_sp(provider_id: str,
                organization: str | None = None,
                available_bytes: int | None = None,
                payee_address: str | None = None):
    """
    Interactively register or update a single Storage Provider on-chain via SPRegistry contract.

    PROVIDER_ID - f0-id (Actor ID) of the SP in Filecoin network.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(sp_address())

    _provider_id = ActorId(provider_id)
    registered_info = SPRegistry().get_provider_view(_provider_id)

    # noinspection PyArgumentList
    provider = SPRegistryProviderInput(
        provider_id=_provider_id,
        organization_address=EthAddress.from_any(organization) if organization else registered_info.organization_address,
        available_bytes=available_bytes if available_bytes is not None else registered_info.available_bytes,
        payee_address=EthAddress.from_any(payee_address) if payee_address else registered_info.payee_address
    )

    commands_utils.register_or_update_sps([provider], sp_signer())
