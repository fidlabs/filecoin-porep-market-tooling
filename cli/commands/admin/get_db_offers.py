import click

from cli import utils
from cli.commands.admin import _utils as admin_utils
from cli.services.web3_service import ActorId


@click.command()
@click.argument("db_id", type=click.IntRange(min=0), required=False)
@click.option("--db-url", envvar="SP_REGISTRY_DATABASE_URL", show_envvar=True, required=True,
              help="SPRegistry database connection string.")
@click.option("--show-all", is_flag=True, default=False,
              help="Whether to return SPs from all organizations or only from those eligible for registration.  [default: false]")
@click.option("--miner-id", required=False,
              help="SPRegistry database miner_id (PoRep Market SP ID) to return.")
@click.option("--organization-address", required=False,
              help="SPRegistry database organization_address to return.")
def get_db_offers(db_url: str,
                  show_all: bool = False,
                  db_id: int | None = None,
                  miner_id: str | None = None,
                  organization_address: str | None = None):
    """
    Get PoRep Market offers from SPRegistry database.

    DB_ID - SPRegistry database organization ID to fetch SPs from. [default: SPs from all organizations eligible for registration]
    """

    click.echo(utils.json_pretty(
        admin_utils.get_db_offers(
            db_url,
            kyc_status="approved" if (not show_all and not db_id) else None,
            organization_db_id=db_id,
            miner_id=ActorId(miner_id) if miner_id else None,
            organization_address=organization_address, )
    ))


@click.command(hidden=True)
def get_mocked_offers():
    click.echo(utils.json_pretty(admin_utils.get_mocked_offers()))
