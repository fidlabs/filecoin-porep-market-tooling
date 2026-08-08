import click

from cli.commands import utils as commands_utils
from cli.commands.sp._sp import sp_address, sp_signer
from cli.services.contracts.sp_registry import SPRegistryProviderInput
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import Web3Service, ActorId, EthAddress


@click.command()
@click.argument("provider-id")
@click.option("--organization", required=False, prompt="Enter organization address",
              help="Organization that runs the SP.  [default: SP_ORGANIZATION env var]")
@click.option("--available-bytes", required=True, prompt="Enter available SP capacity (bytes)",
              type=click.IntRange(min=0), help="Total SP capacity available for deals.")
@click.option("--payee-address", required=True, prompt="Enter SP payee address",
              help="Address receiving SP payments for deals.")
def register_sp(provider_id: str,
                organization: str,
                available_bytes: int,
                payee_address: str):
    """
    Interactively register a single SP on-chain via SPRegistry contract.

    PROVIDER_ID - f0-id (Actor ID) of the Storage Provider in Filecoin network.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(sp_address())

    # noinspection PyArgumentList
    provider = SPRegistryProviderInput(
        provider_id=ActorId(provider_id),
        organization_address=EthAddress.from_any(organization),
        available_bytes=available_bytes,
        payee_address=EthAddress.from_any(payee_address)
    )

    commands_utils.register_sps([provider], sp_signer())
