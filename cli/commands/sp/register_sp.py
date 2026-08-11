import click
import humanfriendly

from cli.commands import utils as commands_utils
from cli.commands.sp._sp import sp_address, sp_signer
from cli.services.contracts.sp_registry import SPRegistryProviderInput, SPRegistry
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import Web3Service, ActorId, EthAddress


@click.command()
@click.argument("provider_id")
@click.option("--organization",
              help="Organization that runs the SP.  [default: SP_ORGANIZATION env var]")
@click.option("--available-capacity",
              help="Total SP disk capacity available for deals in human readable size format (e.g., '1 TiB', 500GiB).")
@click.option("--payee-address",
              help="Address receiving SP payments for deals.")
def register_sp(provider_id: str,
                organization: str | None = None,
                available_capacity: str | None = None,
                payee_address: str | None = None):
    """
    Interactively register or update a single Storage Provider on-chain via SPRegistry contract.

    PROVIDER_ID - f0-id (Actor ID) of the SP in Filecoin network.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(sp_address())

    _provider_id = ActorId(provider_id)

    try:
        registered_info = SPRegistry().get_provider_view(_provider_id)
    except RuntimeError as e:
        registered_info = None

        if not organization or not available_capacity or not payee_address:
            raise click.UsageError(
                "SP is not registered yet. Please provide all required parameters: --organization, --available-capacity, --payee-address"
            ) from e

    # noinspection PyArgumentList
    provider = SPRegistryProviderInput(
        provider_id=_provider_id,
        organization_address=EthAddress.from_any(organization) if organization else registered_info.organization_address,
        available_bytes=humanfriendly.parse_size(available_capacity) if available_capacity is not None else registered_info.available_bytes,
        payee_address=EthAddress.from_any(payee_address) if payee_address else registered_info.payee_address
    )

    commands_utils.register_or_update_sps([provider], sp_signer())
