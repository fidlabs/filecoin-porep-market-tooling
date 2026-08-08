import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.admin import _utils as admin_utils
from cli.commands.admin._admin import admin_address, admin_signer
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import ActorId, Web3Service


@click.command()
@click.argument("provider_id", required=False)
@click.option("--db-url", envvar="SP_REGISTRY_DATABASE_URL", show_envvar=True, required=True,
              help="SPRegistry database connection string.")
@click.option("--db-id", type=click.IntRange(min=0),
              help="Optional SPRegistry database organization ID to register SPs from.")
@click.option("--organization-address",
              help="Optional SPRegistry database organization_address to register SPs from.")
def register_db_sps(db_url: str,
                    db_id: int | None = None,
                    provider_id: str | None = None,
                    organization_address: str | None = None):
    """
    Interactively register SPs and offers from SPRegistry database.

    \b
    1. Fetch and print SPs from SPRegistry database,
    2. register them one by one on-chain via SPRegistry contract,
    3. register each offer on-chain via SPRegistry contract.

    \b
    PROVIDER_ID - Optional SPRegistry database miner_id (PoRep Market SP ID) to register.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(admin_address())

    sps = admin_utils.get_db_sps(db_url,
                                 kyc_status="approved",
                                 organization_db_id=db_id,
                                 provider_id=ActorId(provider_id) if provider_id else None,
                                 organization_address=organization_address)

    if not sps:
        click.echo("No SPs found to register.")
        return

    commands_utils.register_or_update_sps(sps, admin_signer())

    click.echo()

    offers = admin_utils.get_db_offers(db_url,
                                       kyc_status="approved",
                                       organization_db_id=db_id,
                                       provider_id=ActorId(provider_id) if provider_id else None,
                                       organization_address=organization_address)

    if not offers:
        click.echo("No offers found to register.")
        return

    commands_utils.register_offers(offers, admin_signer())


@click.command(hidden=True)
def register_mocked_sps():
    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(admin_address())

    if Web3Service().get_chain_id() == 314:
        utils.confirm("WARNING: Registering mocked SPs and offers on the production network. Continue?",
                      default=False, abort=True)
        click.echo()

    commands_utils.register_or_update_sps(admin_utils.get_mocked_sps(), admin_signer())
    click.echo()
    commands_utils.register_offers(admin_utils.get_mocked_offers(), admin_signer())
