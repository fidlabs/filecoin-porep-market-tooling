import click

from cli import utils
from cli.services.contracts.sp_registry import SPRegistry


@click.command()
def get_sps():
    """
    Get registered SPs from the SPRegistry Smart Contract.
    """

    click.echo(utils.json_pretty(SPRegistry().get_provider_views()))
