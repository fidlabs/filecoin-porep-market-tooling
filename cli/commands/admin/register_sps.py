import click

from cli import utils
from cli.commands.admin import _utils as admin_utils
from cli.commands.admin._admin import admin_address, admin_signer
from cli.services.contracts.sp_registry import (
    SPRegistry,
    SPRegistryOfferInput,
    SPRegistryProviderInput,
    SPRegistryProviderView,
)
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import ActorId, Web3Service


def __update_provider_params(provider: SPRegistryProviderInput,
                             registered_info: SPRegistryProviderView,
                             different_parameters: dict):
    #
    if provider.organization_address != registered_info.organization_address:
        if not utils.confirm(f"organization_address cannot be updated for Storage Provider {provider.provider_id}, continue with other parameters?",
                             default=True):
            #
            click.echo("Skipped this provider")
            return

    if provider.payee_address != registered_info.payee_address:
        if utils.confirm(f"Updating payee_address for Storage Provider {provider.provider_id}: "
                         f"{different_parameters['payee_address']}",
                         default=True,
                         session_id=f"update-{provider.provider_id}"):
            #
            tx_hash = SPRegistry().set_payee(provider.provider_id,
                                             provider.payee_address,
                                             admin_signer())

            click.echo(f"Updated payee_address for Storage Provider {provider.provider_id}: {tx_hash}")

        else:
            click.echo("Skipped this parameter\n")

    if provider.available_bytes != registered_info.available_bytes:
        if utils.confirm(f"Updating available_bytes for Storage Provider {provider.provider_id}: "
                         f"{different_parameters['available_bytes']}",
                         default=True,
                         session_id=f"update-{provider.provider_id}"):
            #
            tx_hash = SPRegistry().update_available_space(provider.provider_id,
                                                          provider.available_bytes,
                                                          admin_signer())

            click.echo(f"Updated available_bytes for Storage Provider {provider.provider_id}: {tx_hash}")

        else:
            click.echo("Skipped this parameter\n")


def _register_sps(providers: list[SPRegistryProviderInput]):
    Web3Service().wait_for_pending_transactions(admin_address())

    for provider in providers:
        is_registered = SPRegistry().is_provider_registered(provider.provider_id)

        if is_registered:
            # update Storage Provider parameters if different from registered ones

            registered_info = SPRegistry().get_provider_view(provider.provider_id)
            different_parameters = {k: {"new": v, "old": getattr(registered_info, k)}
                                    for k, v in provider.__dict__.items() if
                                    getattr(registered_info, k) != getattr(provider, k)}

            if not different_parameters:
                click.echo(f"Storage Provider {provider.provider_id} already registered with same parameters")
                continue

            if not utils.confirm(f"\nStorage Provider {provider.provider_id} already registered with different parameters\n"
                                 f"Do you want to update SP {provider.provider_id} parameters?\n"
                                 f"{utils.json_pretty(different_parameters)}", session_id="update-provider"):
                #
                click.echo("Skipped this provider")
                continue

            __update_provider_params(provider, registered_info, different_parameters)

        else:
            # register Storage Provider with given parameters

            if not utils.confirm(f"\nRegistering Storage Provider with parameters: {provider}", default=True, session_id="register-provider"):
                click.echo("Skipped this provider")
                continue

            if not utils.confirm(f"\nThe organization_address {provider.organization_address} cannot be changed "
                                 f"once registered for provider_id {provider.provider_id}. Are you sure this is correct?"):
                #
                click.echo("Skipped this provider")
                continue

            tx_hash = SPRegistry().register_provider_for(provider, admin_signer())
            click.echo(f"Provider {provider.provider_id} registered: {tx_hash}")


# def __update_offer_params(offer: SPRegistryOfferInput,
#                           registered_info: SPRegistryOfferView,
#                           different_parameters: dict):
#
#     assert offer.provider_id == registered_info.provider_id

    # if (provider.max_deal_duration_days, provider.min_deal_duration_days) != (registered_info.max_deal_duration_days, registered_info.min_deal_duration_days):
    #     _different_parameters = {k: v for k, v in different_parameters.items() if k in ["max_deal_duration_days", "min_deal_duration_days"]}
    #
    #     if utils.confirm(f"Updating (max_deal_duration_days, min_deal_duration_days) for Storage Provider {provider.provider_id}: "
    #                      f"{_different_parameters}",
    #                      default=True,
    #                      session_id=f"update-{provider.provider_id}"):
    #         #
    #         tx_hash = SPRegistry().set_deal_duration_limits(provider.provider_id,
    #                                                         provider.min_deal_duration_days,
    #                                                         provider.max_deal_duration_days,
    #                                                         admin_signer())
    #
    #         click.echo(f"Updated (max_deal_duration_days, min_deal_duration_days) for Storage Provider {provider.provider_id}: {tx_hash}")
    #
    #     else:
    #         click.echo("Skipped this parameter\n")
    #
    # if provider.price_per_sector_per_month != registered_info.price_per_sector_per_month:
    #     if utils.confirm(f"Updating price_per_sector_per_month for Storage Provider {provider.provider_id}: "
    #                      f"{different_parameters['price_per_sector_per_month']}",
    #                      default=True,
    #                      session_id=f"update-{provider.provider_id}"):
    #         #
    #         tx_hash = SPRegistry().set_price(provider.provider_id,
    #                                          provider.price_per_sector_per_month,
    #                                          admin_signer())
    #
    #         click.echo(f"Updated price_per_sector_per_month for Storage Provider {provider.provider_id}: {tx_hash}")
    #
    #     else:
    #         click.echo("Skipped this parameter\n")
    #
    # if provider.capabilities != registered_info.capabilities:
    #     if utils.confirm(f"\nUpdating capabilities for Storage Provider {provider.provider_id}: "
    #                      f"{utils.json_pretty(different_parameters['capabilities'])}",
    #                      default=True,
    #                      session_id=f"update-{provider.provider_id}"):
    #         #
    #         tx_hash = SPRegistry().set_capabilities(provider.provider_id,
    #                                                 provider.capabilities,
    #                                                 admin_signer())
    #
    #         click.echo(f"Updated capabilities for Storage Provider {provider.provider_id}: {tx_hash}")
    #
    #     else:
    #         click.echo("Skipped this parameter\n")


def _register_offers(offers: list[SPRegistryOfferInput]):
    Web3Service().wait_for_pending_transactions(admin_address())

    # TODO ASAP support offer update
    utils.confirm_ok("Current version of CLI / Smart Contracts does not support updating existing offers. "
                     "Each offer in the SP Registry DB will be considered new. "
                     "Please double-check each offer before sumitting it on-chain.")

    for offer in offers:
        is_registered = False

        if is_registered:
            # update PoRep Market Offer parameters if different from registered ones
            # __update_offer_params
            pass
        else:
            # register PoRep Market Offer with given parameters

            if not utils.confirm(f"\nRegistering PoRep Market Offer with parameters: {offer}", default=True, session_id="register-offer"):
                click.echo("Skipped this offer")
                continue

            tx_hash = SPRegistry().create_offer(offer, admin_signer())
            click.echo(f"Offer for provider {offer.provider_id} registered: {tx_hash}")


@click.command()
@click.argument("db_id", type=click.IntRange(min=0), required=False)
@click.option("--db-url", envvar="SP_REGISTRY_DATABASE_URL", show_envvar=True, required=True,
              help="SPRegistry database connection string.")
@click.option("--miner-id", required=False,
              help="SPRegistry database miner_id (PoRep Market SP ID) to register.")
@click.option("--organization-address", required=False,
              help="SPRegistry database organization_address to register.")
def register_db_sps(db_url: str,
                    db_id: int | None = None,
                    miner_id: str | None = None,
                    organization_address: str | None = None):
    """
    Interactively register SPs and offers from SPRegistry database.

    \b
    1. Fetch and print SPs from SPRegistry database,
    2. register them one by one on-chain via SPRegistry contract,
    3. register each offer on-chain via SPRegistry contract.

    DB_ID - SPRegistry database organization ID to register SPs from.
    """

    SelfUpdateService.check_and_prompt(manual=False)

    _register_sps(admin_utils.get_db_sps(db_url,
                                         kyc_status="approved",
                                         organization_db_id=db_id,
                                         miner_id=ActorId(miner_id) if miner_id else None,
                                         organization_address=organization_address))

    _register_offers(admin_utils.get_db_offers(db_url,
                                               kyc_status="approved",
                                               organization_db_id=db_id,
                                               miner_id=ActorId(miner_id) if miner_id else None,
                                               organization_address=organization_address))


@click.command(hidden=True)
def register_devnet_sps():
    SelfUpdateService.check_and_prompt(manual=False)

    _register_sps(admin_utils.get_devnet_sps())
    _register_offers(admin_utils.get_devnet_offers())
