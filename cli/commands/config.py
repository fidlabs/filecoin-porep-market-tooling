import click

from cli.commands import utils as commands_utils


@click.command()
def config():
    """
    Display the current config.
    """

    commands_utils.print_info()
