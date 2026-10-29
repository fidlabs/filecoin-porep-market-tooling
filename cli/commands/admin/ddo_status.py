import click

from cli.commands import utils as commands_utils
from cli.commands.admin._admin import admin_signer


@click.command("ddo-status")
@click.argument("deal_id", type=click.IntRange(min=1))
@click.option("--curio-url",
              help="Override Curio Market endpoint discovery. Intended for development/debugging.")
# TODO json output
def ddo_status(deal_id: int, curio_url: str | None = None):
    """
    Print Curio DDO statuses for all pieces of a PoRep Market deal.

    \b
    DEAL_ID - PoRep Market deal ID.
    """

    commands_utils.ddo_status(deal_id, admin_signer(), curio_url)
