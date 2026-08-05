import click

DRY_RUN: bool = False


@click.group(context_settings={"max_content_width": 160})
@click.option("--dry-run", envvar="DRY_RUN", show_envvar=True, is_flag=True, default=False,
              help="Enable dry-run mode, which only simulates transactions.")
def cli(dry_run: bool = False):
    """
    \b
    CLI tool for interacting with Filecoin PoRep Market smart contracts.
    Developed for admins, clients, and SPs to manage their market interactions from command line.
    """

    global DRY_RUN
    DRY_RUN = dry_run


def is_dry_run() -> bool:
    return DRY_RUN
