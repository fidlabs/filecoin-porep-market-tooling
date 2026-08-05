import click

from cli.services.self_update import SelfUpdateService


@click.command()
def self_update():
    """
    Update the CLI tool to the latest version from the remote Git repository.
    """

    SelfUpdateService.check_and_prompt(manual=True)
