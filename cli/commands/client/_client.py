import click
from eth_account.types import PrivateKeyType
from eth_typing import HexStr

from cli import utils
from cli.commands import utils as commands_utils
from cli.services.txsigner import TxSigner, PrivateKeyTxSigner, LotusWalletTxSigner
from cli.services.web3_service import EthAddress, Web3Service

CLIENT_ADDRESS: str | None = None
CLIENT_ETH_ADDRESS: EthAddress | None = None
CLIENT_PRIVATE_KEY: str | None = None
CLIENT_LOTUS_WALLET: str | None = None


@click.group()
@click.option("--private-key", envvar="CLIENT_PRIVATE_KEY", hidden=True)
@click.option("--address", envvar="CLIENT_ADDRESS", show_envvar=True,
              help="Client address to use. Can be any format possible.  [default: derived from the provided private key / lotus wallet]")
@click.option("--confirm-info", is_flag=True, default=False,
              help="Confirm current account info before executing command.  [default: false]")
@click.option("--lotus-wallet", envvar="CLIENT_LOTUS_WALLET", show_envvar=True,
              help="Client Lotus wallet address used for signing blockchain transactions. Must be delegated f410 address or standard EVM address.")
def client(address: str | None = None, private_key: str | None = None, confirm_info: bool = False, lotus_wallet: str | None = None):
    """
    Client commands for interacting with the PoRep Market.
    """

    if private_key:
        global CLIENT_PRIVATE_KEY
        CLIENT_PRIVATE_KEY = private_key
    else:
        global CLIENT_LOTUS_WALLET
        CLIENT_LOTUS_WALLET = lotus_wallet

    global CLIENT_ADDRESS
    CLIENT_ADDRESS = address

    if confirm_info:
        _info()
        utils.confirm("\n\nContinue?", default=True, abort=True)
        click.echo("\n\n")


# lazy initialization
def client_address() -> EthAddress:
    global CLIENT_ETH_ADDRESS

    if not CLIENT_ETH_ADDRESS:
        if CLIENT_ADDRESS:
            CLIENT_ETH_ADDRESS = EthAddress.from_any(CLIENT_ADDRESS)
        elif CLIENT_PRIVATE_KEY:
            CLIENT_ETH_ADDRESS = EthAddress.from_private_key(HexStr(CLIENT_PRIVATE_KEY))
        elif CLIENT_LOTUS_WALLET:
            CLIENT_ETH_ADDRESS = EthAddress.from_any(CLIENT_LOTUS_WALLET)
        else:
            raise click.ClickException("Client address is not set and cannot be derived from private key or Lotus wallet")

        if CLIENT_ADDRESS and CLIENT_ETH_ADDRESS != CLIENT_ADDRESS:
            click.echo(f"Converted client address {CLIENT_ADDRESS} to EVM 0x-address {CLIENT_ETH_ADDRESS}.")
            click.echo(f"Set client address to {CLIENT_ETH_ADDRESS} to avoid this prompt next time")
            click.echo("\n")

    assert CLIENT_ETH_ADDRESS
    return CLIENT_ETH_ADDRESS


# lazy initialization
def client_signer() -> TxSigner:
    global CLIENT_PRIVATE_KEY

    if CLIENT_PRIVATE_KEY:
        if CLIENT_ADDRESS:
            validate_address_matches_private_key(client_address(), HexStr(CLIENT_PRIVATE_KEY))

        return PrivateKeyTxSigner(HexStr(CLIENT_PRIVATE_KEY))

    elif CLIENT_LOTUS_WALLET:
        return LotusWalletTxSigner(CLIENT_LOTUS_WALLET, utils.get_env_required("CLIENT_LOTUS_TOKEN"))

    else:
        CLIENT_PRIVATE_KEY = click.prompt("Client private key", hide_input=True)
        assert CLIENT_PRIVATE_KEY
        return PrivateKeyTxSigner(HexStr(CLIENT_PRIVATE_KEY))


def _info():
    try:
        _client_address = client_address() if CLIENT_PRIVATE_KEY or CLIENT_LOTUS_WALLET else None
    # pylint: disable=broad-exception-caught
    except Exception as e:
        _client_address = None
        click.echo(f"Error getting client address: {e}")

    click.echo(f"Client wallet private key: {utils.private_str_to_log_str(CLIENT_PRIVATE_KEY)}")
    commands_utils.print_info(_client_address, "Client")


@click.command()
@click.option("--test-keys", is_flag=True, default=False,
              help="Fail if the private key does not matches provided address.  [default: false]")
def info(test_keys: bool = False):
    """
    Display the current client info.
    """

    if test_keys:
        _ = client_signer()  # validate only

    _info()


@click.command()
def wait():
    """
    Wait for all pending transactions from the current private key to be mined and exit.
    """

    Web3Service().wait_for_pending_transactions(client_address())


def validate_address_matches_private_key(address: EthAddress, private_key: PrivateKeyType | None):
    if not private_key:
        raise click.ClickException("Private key is not set")

    derived_address = EthAddress.from_private_key(private_key)

    if derived_address != address:
        raise click.ClickException(f"Address {address} does not match private key {utils.private_str_to_log_str(private_key)} (expected: {derived_address})")
