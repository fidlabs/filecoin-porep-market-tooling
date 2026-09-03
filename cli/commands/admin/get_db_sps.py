import click

from cli import utils
from cli.commands.admin import _utils as admin_utils
from cli.services.web3_service import ActorId


@click.command()
@click.argument("provider_id", required=False)
@click.option("--db-url", envvar="SP_REGISTRY_DATABASE_URL", show_envvar=True, required=True,
              help="SPRegistry database connection string.")
@click.option("--db-id", type=click.IntRange(min=0),
              help="Optional SPRegistry database organization ID to return SPs from.")
@click.option("--show-all", is_flag=True, default=False,
              help="Whether to return SPs from all organizations or only from those eligible for registration.  [default: false]")
@click.option("--organization-address",
              help="Optional SPRegistry database organization_address to return SPs from.")
def get_db_sps(db_url: str,
               show_all: bool = False,
               db_id: int | None = None,
               provider_id: str | None = None,
               organization_address: str | None = None):
    """
    Get SPs from SPRegistry database.

    \b
    PROVIDER_ID - Optional SPRegistry database miner_id (PoRep Market SP ID) to return.
    """

    click.echo(utils.json_pretty(
        admin_utils.get_db_sps(
            db_url,
            kyc_status="approved" if (not show_all and not db_id) else None,
            organization_db_id=db_id,
            provider_id=ActorId(provider_id) if provider_id else None,
            organization_address=organization_address,
        )
    ))


@click.command(hidden=True)
def get_mocked_sps():
    click.echo(utils.json_pretty(admin_utils.get_mocked_sps()))
