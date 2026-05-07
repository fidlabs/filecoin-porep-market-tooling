import click

from cli import utils
from cli.services.web3_service import ActorId, EthAddress, FilAddress


@click.command("convert")
@click.argument("addr")
def convert(addr: str):
    """Convert ADDR to all address formats and output as JSON."""
    result = {}

    for key, fn in [
        ("ethAddress", EthAddress.parse),
        ("filAddress", FilAddress.parse),
        ("actorId",    ActorId.parse),
    ]:
        try:
            result[key] = str(fn(addr))
        except Exception as e:
            result[key] = f"ERROR: {e}"

    click.echo(utils.json_pretty(result))
