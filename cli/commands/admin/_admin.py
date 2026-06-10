import click
from eth_typing import HexStr

from cli import utils
from cli.commands import utils as commands_utils
from cli.services.txsigner import TxSigner, PrivateKeyTxSigner, LotusWalletTxSigner
from cli.services.web3_service import EthAddress, Web3Service

ADMIN_PRIVATE_KEY: str | None = None
ADMIN_LOTUS_WALLET: str | None = None


@click.group()
@click.option("--private-key", envvar="ADMIN_PRIVATE_KEY", hidden=True)
@click.option("--confirm-info", is_flag=True, default=False,
              help="Confirm current account info before executing command.  [default: false]")
@click.option("--lotus-wallet", envvar="ADMIN_LOTUS_WALLET", show_envvar=True,
              help="Admin Lotus wallet address used for signing blockchain transactions. Must be delegated f410 address or standard EVM address.")
def admin(private_key: str | None = None, confirm_info: bool = False, lotus_wallet: str | None = None):
    """
    Admin commands for managing the PoRep Market.
    """

    if private_key:
        global ADMIN_PRIVATE_KEY
        ADMIN_PRIVATE_KEY = private_key
    else:
        global ADMIN_LOTUS_WALLET
        ADMIN_LOTUS_WALLET = lotus_wallet

    if confirm_info:
        _info()
        utils.confirm("\n\nContinue?", default=True, abort=True)
        click.echo("\n\n")


def admin_address() -> EthAddress:
    return admin_signer().address()


# lazy initialization
def admin_signer() -> TxSigner:
    global ADMIN_PRIVATE_KEY

    if ADMIN_PRIVATE_KEY:
        return PrivateKeyTxSigner(HexStr(ADMIN_PRIVATE_KEY))

    elif ADMIN_LOTUS_WALLET:
        return LotusWalletTxSigner(ADMIN_LOTUS_WALLET, utils.get_env_required("ADMIN_LOTUS_TOKEN"))

    else:
        ADMIN_PRIVATE_KEY = click.prompt("Admin private key", hide_input=True)
        assert ADMIN_PRIVATE_KEY
        return PrivateKeyTxSigner(HexStr(ADMIN_PRIVATE_KEY))


def _info():
    try:
        _admin_address = admin_address() if ADMIN_PRIVATE_KEY or ADMIN_LOTUS_WALLET else None
        _admin_address_err = ""
    # pylint: disable=broad-exception-caught
    except Exception as e:
        _admin_address = None
        _admin_address_err = f"Error getting account address: {e}"

    click.echo(f"Admin wallet eth-address: {_admin_address or _admin_address_err}")
    click.echo(f"Admin wallet private key: {utils.private_str_to_log_str(ADMIN_PRIVATE_KEY)}")
    commands_utils.print_info(_admin_address, "Admin")


@click.command()
def info():
    """
    Display the current admin info.
    """

    _info()


@click.command()
def wait():
    """
    Wait for all pending transactions from the current private key to be mined and exit.
    """

    Web3Service().wait_for_pending_transactions(admin_address())
