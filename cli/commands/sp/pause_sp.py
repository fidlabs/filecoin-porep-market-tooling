import click

from cli.commands import utils as commands_utils
from cli.commands.sp._sp import sp_address, sp_signer
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import Web3Service, ActorId


@click.command()
@click.argument("provider_id")
def pause_sp(provider_id: str):
    """
    Pause a Storage Provider in the SPRegistry Smart Contract.

    PROVIDER_ID - Storage Provider ID to pause.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(sp_address())

    commands_utils.pause_sp(ActorId(provider_id), sp_signer())


@click.command()
@click.argument("provider_id")
def unpause_sp(provider_id: str):
    """
    Unpause a Storage Provider in the SPRegistry Smart Contract.

    PROVIDER_ID - Storage Provider ID to unpause.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(sp_address())

    commands_utils.unpause_sp(ActorId(provider_id), sp_signer())
