import click

from cli import utils
from cli.commands.admin import _utils as admin_utils
from cli.services.web3_service import ActorId


@click.command()
@click.argument("provider_id", required=False)
@click.option("--db-url", envvar="SP_REGISTRY_DATABASE_URL", show_envvar=True, required=True,
              help="SPRegistry database connection string.")
@click.option("--organization-db-id", type=click.IntRange(min=0),
              help="Optional SPRegistry database organization ID to return offers from.")
@click.option("--show-all", is_flag=True, default=False,
              help="Whether to return offers from all organizations or only from those eligible for registration.  [default: false]")
@click.option("--organization-address",
              help="Optional SPRegistry database organization_address to return offers from.")
def get_db_offers(db_url: str,
                  show_all: bool = False,
                  organization_db_id: int | None = None,
                  provider_id: str | None = None,
                  organization_address: str | None = None):
    """
    Get PoRep Market offers from SPRegistry database.

    \b
    PROVIDER_ID - Optional SPRegistry database miner_id (PoRep Market SP ID) to return offers from.
    """

    click.echo(utils.json_pretty(
        admin_utils.get_db_offers(
            db_url,
            kyc_status="approved" if (not show_all and not organization_db_id) else None,
            organization_db_id=organization_db_id,
            provider_id=ActorId(provider_id) if provider_id else None,
            organization_address=organization_address
        )
    ))


@click.command(hidden=True)
def get_mocked_offers():
    click.echo(utils.json_pretty(admin_utils.get_mocked_offers()))
