import click
from eth_account.types import PrivateKeyType

from cli import utils
from cli.commands import utils as commands_utils
from cli.services.web3_service import EthAddress, Web3Service

ADMIN_PRIVATE_KEY: str | None = None


@click.group()
@click.option("--private-key", envvar="ADMIN_PRIVATE_KEY", hidden=True)
@click.option("--confirm-info", is_flag=True, default=False, show_default=True,
              help="Confirm current account info before executing command.  [default: false]")
def admin(private_key: str | None = None, confirm_info: bool = False):
    """
    Admin commands for managing the PoRep Market.
    """

    global ADMIN_PRIVATE_KEY
    ADMIN_PRIVATE_KEY = private_key

    if confirm_info:
        _info()
        click.confirm("\n\nContinue?", default=True, abort=True)
        click.echo("\n\n")


def admin_address() -> EthAddress:
    return EthAddress.from_private_key(admin_private_key())


# lazy initialization
def admin_private_key() -> PrivateKeyType:
    global ADMIN_PRIVATE_KEY

    if not ADMIN_PRIVATE_KEY:
        ADMIN_PRIVATE_KEY = click.prompt("Admin private key", hide_input=True)

    assert ADMIN_PRIVATE_KEY
    return ADMIN_PRIVATE_KEY


def _info():
    click.echo(f"Admin wallet address: {admin_address() if ADMIN_PRIVATE_KEY else ''}")
    click.echo(f"Admin wallet private key: {utils.private_str_to_log_str(ADMIN_PRIVATE_KEY)}")
    click.echo()
    commands_utils.print_info()


@click.command()
def info():
    """
    Display the current admin info.
    """

    _info()


@click.command()
def wait():
    """
    Wait for all pending transactions from the current private key to be mined and exit. Useful when executing a series of commands.
    """

    Web3Service().wait_for_pending_transactions(admin_address())
