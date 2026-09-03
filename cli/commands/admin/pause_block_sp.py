import click

from cli.commands import utils as commands_utils
from cli.commands.admin._admin import admin_address, admin_signer
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
    Web3Service().wait_for_pending_transactions(admin_address())

    commands_utils.pause_sp(ActorId(provider_id), admin_signer())


@click.command()
@click.argument("provider_id")
def unpause_sp(provider_id: str):
    """
    Unpause a Storage Provider in the SPRegistry Smart Contract.

    PROVIDER_ID - Storage Provider ID to unpause.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(admin_address())

    commands_utils.unpause_sp(ActorId(provider_id), admin_signer())


@click.command()
@click.argument("provider_id")
def block_sp(provider_id: str):
    """
    Block a Storage Provider in the SPRegistry Smart Contract.

    PROVIDER_ID - Storage Provider ID to block.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(admin_address())

    commands_utils.block_sp(ActorId(provider_id), admin_signer())


@click.command()
@click.argument("provider_id")
def unblock_sp(provider_id: str):
    """
    Unblock a Storage Provider in the SPRegistry Smart Contract.

    PROVIDER_ID - Storage Provider ID to unblock.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(admin_address())

    commands_utils.unblock_sp(ActorId(provider_id), admin_signer())
