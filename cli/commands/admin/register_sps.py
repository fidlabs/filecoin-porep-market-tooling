import click

from cli import utils
from cli.commands.admin import _utils as admin_utils
from cli.commands.admin._admin import admin_private_key, admin_address
from cli.services.contracts.sp_registry import SPRegistry, SPRegistryProvider, SPRegistryProviderInfo
from cli.services.web3_service import Web3Service, ActorId


def __update_provider_params(provider: SPRegistryProvider | SPRegistryProviderInfo,
                             registered_info: SPRegistryProvider,
                             different_parameters: dict):
    #
    if provider.organization_address != registered_info.organization_address:
        raise RuntimeError(f"Organization address cannot be updated for Storage Provider {provider.provider_id}")

    if (provider.max_deal_duration_days, provider.min_deal_duration_days) != (registered_info.max_deal_duration_days, registered_info.min_deal_duration_days):
        _different_parameters = {k: v for k, v in different_parameters.items() if k in ["max_deal_duration_days", "min_deal_duration_days"]}

        if click.confirm(
                f"Updating (max_deal_duration_days, min_deal_duration_days) for Storage Provider {provider.provider_id}: "
                f"{_different_parameters}",
                default=True):
            #
            tx_hash = SPRegistry().set_deal_duration_limits(provider.provider_id,
                                                            provider.min_deal_duration_days,
                                                            provider.max_deal_duration_days,
                                                            admin_private_key())

            click.echo(f"Updated deal duration limits for Storage Provider {provider.provider_id}: {tx_hash}")

        else:
            click.echo("Skipped this parameter\n")

    if provider.price_per_sector_per_month != registered_info.price_per_sector_per_month:
        if click.confirm(
                f"Updating price_per_sector_per_month for Storage Provider {provider.provider_id}: "
                f"{different_parameters['price_per_sector_per_month']}",
                default=True):
            #
            tx_hash = SPRegistry().set_price(provider.provider_id,
                                             provider.price_per_sector_per_month,
                                             admin_private_key())

            click.echo(f"Updated price per sector per month for Storage Provider {provider.provider_id}: {tx_hash}")

        else:
            click.echo("Skipped this parameter\n")

    if provider.capabilities != registered_info.capabilities:
        if click.confirm(
                f"\nUpdating capabilities for Storage Provider {provider.provider_id}: "
                f"{utils.json_pretty(different_parameters['capabilities'])}",
                default=True):
            #
            tx_hash = SPRegistry().set_capabilities(provider.provider_id,
                                                    provider.capabilities,
                                                    admin_private_key())

            click.echo(f"Updated capabilities for Storage Provider {provider.provider_id}: {tx_hash}")

        else:
            click.echo("Skipped this parameter\n")

    if provider.payee_address != registered_info.payee_address:
        if click.confirm(
                f"Updating payee_address for Storage Provider {provider.provider_id}: "
                f"{different_parameters['payee_address']}",
                default=True):
            #
            tx_hash = SPRegistry().set_payee(provider.provider_id,
                                             provider.payee_address,
                                             admin_private_key())

            click.echo(f"Updated payee address for Storage Provider {provider.provider_id}: {tx_hash}")

        else:
            click.echo("Skipped this parameter\n")

    if provider.available_bytes != registered_info.available_bytes:
        if click.confirm(
                f"Updating available_bytes for Storage Provider {provider.provider_id}: "
                f"{different_parameters['available_bytes']}",
                default=True):
            #
            tx_hash = SPRegistry().update_available_space(provider.provider_id,
                                                          provider.available_bytes,
                                                          admin_private_key())

            click.echo(f"Updated available bytes for Storage Provider {provider.provider_id}: {tx_hash}")

        else:
            click.echo("Skipped this parameter\n")


# TODO LATER print register provider at the end?
def _register_sps(providers: list[SPRegistryProvider]):
    Web3Service().wait_for_pending_transactions(admin_address())

    for provider in providers:
        is_registered = SPRegistry().is_provider_registered(provider.provider_id)

        if is_registered:
            # update Storage Provider parameters if different from registered ones

            registered_info = SPRegistry().get_provider_info(provider.provider_id)
            assert registered_info

            different_parameters = {k: {"new": v, "old": getattr(registered_info, k)}
                                    for k, v in provider.__dict__.items() if
                                    getattr(registered_info, k) != getattr(provider, k)}

            if not different_parameters:
                click.echo(f"Provider {provider.provider_id} already registered with same parameters, skipping...")
                continue

            if provider.organization_address != registered_info.organization_address:
                click.echo(
                    f"\nCannot update Storage Provider info: different organization_address for provider {provider.provider_id}: "
                    f"{different_parameters['organization_address']}")
                #
                continue

            if not click.confirm(f"\nProvider {provider.provider_id} already registered with different parameters\n"
                                 f"Do you want to update Storage Provider {provider.provider_id} parameters?\n"
                                 f"{utils.json_pretty(different_parameters)}"):
                #
                click.echo("Skipped this provider")
                continue

            __update_provider_params(provider, registered_info, different_parameters)

        else:
            # register Storage Provider with given parameters

            if not click.confirm(f"\nRegistering Storage Provider with parameters: {provider}", default=True):
                click.echo("Skipped this provider")
                continue

            if not click.confirm(f"\nThe organization_address {provider.organization_address} cannot be changed "
                                 f"once registered for provider_id {provider.provider_id}. Are you sure this is correct?"):
                #
                click.echo("Skipped this provider")
                continue

            tx_hash = SPRegistry().register_provider_for(provider, admin_private_key())
            click.echo(f"Provider {provider.provider_id} registered: {tx_hash}")


@click.command()
@click.argument("db_id", type=click.IntRange(min=0), required=False)
@click.option("--db-url", envvar="SP_REGISTRY_DATABASE_URL", show_envvar=True, required=True,
              help="SPRegistry database connection string.")
@click.option("--indexing-pct", type=click.IntRange(0, 100), default=0, show_default=True,
              help="IPNI indexing guarantee in percentage to use; 0 means \"don't support\".", )
@click.option("--miner-id", required=False,
              help="SPRegistry database miner_id (PoRep Market SP ID) to register.")
@click.option("--organization-address", required=False,
              help="SPRegistry database organization_address to register.")
def register_db_sps(db_url: str,
                    db_id: int | None = None,
                    indexing_pct: int = 0,
                    miner_id: str | None = None,
                    organization_address: str | None = None):
    """
    Interactively register SPs from SPRegistry database.

    \b
    1. Fetch and print SPs from SPRegistry database,
    2. register them one by one on-chain via SPRegistry contract.

    DB_ID - SPRegistry database organization id to register SPs from.
    """

    _register_sps(admin_utils.get_db_sps(db_url,
                                         kyc_status="approved",
                                         organization_id=db_id,
                                         indexing_pct=indexing_pct,
                                         miner_id=ActorId(miner_id) if miner_id else None,
                                         organization_address=organization_address))


@click.command(hidden=True)
def register_devnet_sps():
    _register_sps(admin_utils.get_devnet_sps())
