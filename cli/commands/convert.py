import click

from cli import utils
from cli.services.web3_service import EthAddress, FilAddress, ActorId


@click.command()
@click.argument("xinput")
def convert(xinput: str):
    """
    Convert XINPUT to all address formats.

    XINPUT - can be Ethereum address, Filecoin address, or ActorId
    """

    def try_call(func):
        try:
            return func()
        except (ValueError, RuntimeError) as e:
            return f"Error: {str(e)}"

    click.echo(utils.json_pretty({
        "input": xinput,
        "ethAddress": try_call(lambda: EthAddress.from_any(xinput)),
        "filAddress": try_call(lambda: FilAddress.from_any(xinput)),
        "actorId": try_call(lambda: ActorId.from_any(xinput)),
    }))
