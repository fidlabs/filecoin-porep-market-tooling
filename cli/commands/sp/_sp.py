import click
from eth_typing import HexStr

from cli import utils
from cli.commands import utils as commands_utils
from cli.services.txsigner import TxSigner, PrivateKeyTxSigner, LotusWalletTxSigner
from cli.services.web3_service import EthAddress, Web3Service, FilAddress

SP_ORGANIZATION: str | None = None
SP_ORGANIZATION_ADDRESS: str | None = None
SP_PRIVATE_KEY: str | None = None
SP_LOTUS_WALLET: str | None = None


@click.group()
@click.option("--organization", envvar="SP_ORGANIZATION", show_envvar=True, help="Organization address to manage SPs from.")
@click.option("--private-key", envvar="SP_PRIVATE_KEY", hidden=True)
@click.option("--confirm-info", is_flag=True, default=False,
              help="Confirm current account info before executing command.  [default: false]")
@click.option("--lotus-wallet", envvar="SP_LOTUS_WALLET", show_envvar=True,
              help="SP Lotus wallet address used for signing blockchain transactions. Must be delegated f410 address or standard EVM address.")
def sp(private_key: str | None = None, organization: str | None = None, confirm_info: bool = False, lotus_wallet: str | None = None):
    """
    Storage Provider commands for interacting with the PoRep Market.
    """

    if private_key:
        global SP_PRIVATE_KEY
        SP_PRIVATE_KEY = private_key
    else:
        global SP_LOTUS_WALLET
        SP_LOTUS_WALLET = lotus_wallet

    global SP_ORGANIZATION
    SP_ORGANIZATION = organization

    if confirm_info:
        _info()
        utils.confirm("\n\nContinue?", default=True, abort=True)
        click.echo("\n\n")


# TODO from_any?
# lazy initialization
def sp_organization_address() -> EthAddress:
    if not SP_ORGANIZATION:
        raise click.ClickException("SP organization is not set")

    global SP_ORGANIZATION_ADDRESS

    if not SP_ORGANIZATION_ADDRESS:
        if FilAddress.is_filecoin_address(SP_ORGANIZATION):
            SP_ORGANIZATION_ADDRESS = str(EthAddress.from_filecoin_address(SP_ORGANIZATION))

            if not utils.confirm(f"Converted SP organization {SP_ORGANIZATION} Filecoin f-address "
                                 f"to EVM 0x-address {SP_ORGANIZATION_ADDRESS}. "
                                 f"Continue?",
                                 default=True):
                raise click.Abort()
            else:
                click.echo(f"Set SP organization to {SP_ORGANIZATION_ADDRESS} to avoid this prompt next time")
                click.echo("\n")
        else:
            SP_ORGANIZATION_ADDRESS = SP_ORGANIZATION

    assert SP_ORGANIZATION_ADDRESS
    return EthAddress(SP_ORGANIZATION_ADDRESS)


# returns SP's wallet address which might be different that sp_organization_address()
def sp_address() -> EthAddress:
    return sp_signer().address()


# lazy initialization
def sp_signer() -> TxSigner:
    global SP_PRIVATE_KEY

    if SP_PRIVATE_KEY:
        return PrivateKeyTxSigner(HexStr(SP_PRIVATE_KEY))

    elif SP_LOTUS_WALLET:
        return LotusWalletTxSigner(SP_LOTUS_WALLET, utils.get_env_required("SP_LOTUS_TOKEN"))

    else:
        SP_PRIVATE_KEY = click.prompt("SP private key", hide_input=True)
        assert SP_PRIVATE_KEY
        return PrivateKeyTxSigner(HexStr(SP_PRIVATE_KEY))


def _info():
    try:
        _sp_address = sp_address() if SP_PRIVATE_KEY or SP_LOTUS_WALLET else None
        _sp_address_err = ""
    # pylint: disable=broad-exception-caught
    except Exception as e:
        _sp_address = None
        _sp_address_err = f"Error getting account address: {e}"

    click.echo(f"SP organization address: {sp_organization_address() if SP_ORGANIZATION else ''}")
    click.echo(f"SP organization: {SP_ORGANIZATION or ''}")
    click.echo()
    click.echo(f"SP wallet eth-address: {_sp_address or _sp_address_err}")
    click.echo(f"SP wallet private key: {utils.private_str_to_log_str(SP_PRIVATE_KEY)}")
    commands_utils.print_info(_sp_address, "SP wallet")


@click.command()
def info():
    """
    Display the current SP info.
    """

    _info()


@click.command()
def wait():
    """
    Wait for all pending transactions from the current private key to be mined and exit.
    """

    Web3Service().wait_for_pending_transactions(sp_address())
