import click
from eth_account.types import PrivateKeyType
from web3.auto import w3

from cli import utils
from cli.commands import utils as commands_utils
from cli.services.web3_service import EthAddress, Web3Service

CLIENT_ADDRESS: str | None = None
CLIENT_PRIVATE_KEY: str | None = None


@click.group()
@click.option("--address", help="Client address to use.  [default: derived from the provided private key]")
@click.option("--private-key", envvar="CLIENT_PRIVATE_KEY", hidden=True)
@click.option("--confirm-info", is_flag=True, default=False, show_default=True,
              help="Confirm current account info before executing command.  [default: false]")
def client(address: str | None = None, private_key: str | None = None, confirm_info: bool = False):
    """
    Client commands for interacting with the PoRep Market.
    """

    global CLIENT_PRIVATE_KEY
    CLIENT_PRIVATE_KEY = private_key

    global CLIENT_ADDRESS
    CLIENT_ADDRESS = address

    if confirm_info:
        _info()
        utils.confirm("\n\nContinue?", default=True, abort=True)
        click.echo("\n\n")


# lazy initialization
def client_address() -> EthAddress:
    global CLIENT_ADDRESS

    if not CLIENT_ADDRESS:
        if CLIENT_PRIVATE_KEY:
            CLIENT_ADDRESS = w3.eth.account.from_key(CLIENT_PRIVATE_KEY).address
        else:
            raise click.ClickException("Neither client address nor private key is set")

    assert CLIENT_ADDRESS
    return EthAddress(CLIENT_ADDRESS)


# lazy initialization
def client_private_key() -> PrivateKeyType:
    global CLIENT_PRIVATE_KEY

    if not CLIENT_PRIVATE_KEY:
        CLIENT_PRIVATE_KEY = click.prompt("Client private key", hide_input=True)

    commands_utils.validate_address_matches_private_key(client_address(), CLIENT_PRIVATE_KEY)

    assert CLIENT_PRIVATE_KEY
    return CLIENT_PRIVATE_KEY


def _info():
    click.echo(f"Client wallet address: {CLIENT_ADDRESS or ''}")
    click.echo(f"Client wallet private key: {utils.private_str_to_log_str(CLIENT_PRIVATE_KEY)}")
    click.echo()
    commands_utils.print_info()


@click.command()
@click.option("--test-keys", is_flag=True, default=False, show_default=True,
              help="Fail if the private key does not matches provided address.  [default: False]")
def info(test_keys: bool = False):
    """
    Display the current client info.
    """

    if test_keys:
        _ = client_private_key()  # validate only

    _info()


@click.command()
def wait():
    """
    Wait for all pending transactions from the current private key to be mined and exit. Useful when executing a series of commands.
    """

    Web3Service().wait_for_pending_transactions(client_address())
