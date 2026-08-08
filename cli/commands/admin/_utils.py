import click
import humanfriendly

from cli import utils
from cli.services.contracts.erc20_contract import ERC20Contract
from cli.services.contracts.porep_market import PoRepMarket, PoRepMarketSLIThresholds
from cli.services.contracts.sp_registry import (
    SPRegistryOfferInput,
    SPRegistryOfferPaymentInput,
    SPRegistryOfferTerms,
    SPRegistryProviderInput,
)
from cli.services.contracts.usdc_token import USDCToken
from cli.services.sp_registry_db import SPRegistryDB
from cli.services.web3_service import ActorId, EthAddress, FilAddress


def get_db_offers(db_url: str,
                  kyc_status: str | None = None,
                  organization_db_id: int | None = None,
                  miner_id: ActorId | None = None,
                  organization_address: str | None = None) -> list[SPRegistryOfferInput]:
    #
    EPOCHS_IN_MONTH = PoRepMarket().get_epochs_in_month()
    EPOCHS_IN_DAY = EPOCHS_IN_MONTH // 30  # PoRep Market smart contracts assumes month == 30 days
    assert EPOCHS_IN_DAY * 30 == EPOCHS_IN_MONTH

    def months_to_epochs(months: int) -> int:
        return months * EPOCHS_IN_MONTH

    def months_to_days(months: int) -> int:
        # PoRep Market smart contracts assumes month == 30 days
        return months * 30

    def days_to_epochs(days: int) -> int:
        return days * EPOCHS_IN_DAY

    def sla_class_to_sli_thresholds(sla_class: str) -> PoRepMarketSLIThresholds:
        sla_class = sla_class.lower()

        if sla_class == "accessible_storage":
            # noinspection PyArgumentList
            return PoRepMarketSLIThresholds(
                retrievability_bps=8000,  # 80 %
                bandwidth_bytes_per_second=322122547,  # 300 MiB per second
                latency_ms=0,  # TODO ASAP
                indexing_pct=100
            )

        elif sla_class == "premium_storage":
            # noinspection PyArgumentList
            return PoRepMarketSLIThresholds(
                retrievability_bps=10000,  # 100 %
                bandwidth_bytes_per_second=1073741824,  # 1 GiB per second
                latency_ms=0,  # TODO ASAP
                indexing_pct=100
            )

        elif sla_class == "archival":
            # TODO ASAP
            # noinspection PyArgumentList
            return PoRepMarketSLIThresholds(
                retrievability_bps=0,  # 0 %
                bandwidth_bytes_per_second=0,
                latency_ms=999,
                indexing_pct=0
            )

        if sla_class == "accessible_backup":
            # TODO ASAP
            # noinspection PyArgumentList
            return PoRepMarketSLIThresholds(
                retrievability_bps=0,  # 0 %
                bandwidth_bytes_per_second=0,
                latency_ms=999,
                indexing_pct=0
            )

        else:
            raise ValueError(f"Unsupported sla_class: {sla_class}")

    # noinspection PyPep8Naming
    # pylint: disable=invalid-name
    def payment_type_to_payment_input(payment_type: str, price_per_TiB_usd_tokens: float) -> SPRegistryOfferPaymentInput:
        # noinspection PyShadowingNames
        def payment_type_to_token(payment_type: str) -> ERC20Contract:
            if payment_type == USDCToken().symbol():
                return USDCToken()
            else:
                raise ValueError(f"Unsupported payment type: {payment_type}")

        # noinspection PyPep8Naming,PyShadowingNames
        # pylint: disable=invalid-name
        def price_per_TiB_usd_to_per_32_GiB(price_per_TiB_usd_tokens: float, payment_token: ERC20Contract) -> int:
            price_per_TiB = utils.to_wei(price_per_TiB_usd_tokens, payment_token.decimals())
            price_per_32_GiB = price_per_TiB / (1024 / 32)

            if price_per_32_GiB != int(price_per_32_GiB):
                raise ValueError(f"Precision lost: {price_per_32_GiB:.10f} != {int(price_per_32_GiB)}")

            return int(price_per_32_GiB)

        token = payment_type_to_token(payment_type)

        # noinspection PyArgumentList
        return SPRegistryOfferPaymentInput(
            token=token.address(),
            active=True,
            price_per_32_gib_per_month=price_per_TiB_usd_to_per_32_GiB(price_per_TiB_usd_tokens, token)
        )

    #

    MAX_DEAL_DURATION_DAYS_LIMIT = PoRepMarket().get_max_deal_duration_days()
    MIN_DEAL_DURATION_DAYS_LIMIT = PoRepMarket().get_min_deal_duration_days()
    result: list[SPRegistryOfferInput] = []
    offers = SPRegistryDB(db_url).get_sla_classes(kyc_status=kyc_status,
                                                  organization_id=organization_db_id,
                                                  miner_id=miner_id,
                                                  organization_address=organization_address)

    offers_by_org_id = {}
    for offer in offers:
        if offer.org_id not in offers_by_org_id:
            offers_by_org_id[offer.org_id] = []

        offers_by_org_id[offer.org_id].append(offer)

    for org_offers in offers_by_org_id.values():
        for offer in org_offers:
            if offer.specific_miner_id:
                # TODO ASAP?? support SLA Class with specific miner_id
                utils.confirm_ok("SLA Class with non-null specific_miner_id is not supported yet. Cannot return offers from this SLA Class.")
                break

            try:
                payments = [payment_type_to_payment_input(payment_type, offer.price_per_tib_usd) for payment_type in offer.payment_types]
            except ValueError as e:
                utils.confirm_ok(
                    f"Organization {offer.organization_address} [db_id {offer.org_id}] "
                    f"has an unsupported payment configuration: {e}. "
                    f"Cannot return offers from this organization")
                break

            if offer.kyc_status.strip().lower() != "approved":
                if not utils.confirm(
                        f"Organization {offer.organization_address} [db_id {offer.org_id}] has kyc_status {offer.kyc_status}, which is != approved. "
                        f"Return offers from this organization?",
                        default=bool(organization_db_id)):
                    break

            if months_to_days(offer.deal_duration_min_months) < MIN_DEAL_DURATION_DAYS_LIMIT:
                min_deal_duration_epochs = days_to_epochs(MIN_DEAL_DURATION_DAYS_LIMIT)

                if not utils.confirm(
                        f"Organization {offer.organization_address} [db_id {offer.org_id}] has min deal duration "
                        f"of {months_to_days(offer.deal_duration_min_months)} days which is below the SPRegistry contract minimum "
                        f"of {MIN_DEAL_DURATION_DAYS_LIMIT} days. It will be increased to this value. "
                        f"Return offers from this organization?",
                        default=True,
                        session_id="get-db-offers"):
                    break
            else:
                min_deal_duration_epochs = months_to_epochs(offer.deal_duration_min_months)

            if months_to_days(offer.deal_duration_max_months) > MAX_DEAL_DURATION_DAYS_LIMIT:
                max_deal_duration_epochs = days_to_epochs(MAX_DEAL_DURATION_DAYS_LIMIT)

                if not utils.confirm(
                        f"Organization {offer.organization_address} [db_id {offer.org_id}] has max deal duration "
                        f"of {months_to_days(offer.deal_duration_max_months)} days which exceeds the SPRegistry contract limit "
                        f"of {MAX_DEAL_DURATION_DAYS_LIMIT} days. It will be truncated to this value. "
                        f"Return offers from this organization?",
                        default=True,
                        session_id="get-db-offers"):
                    break
            else:
                max_deal_duration_epochs = months_to_epochs(offer.deal_duration_max_months)

            if min_deal_duration_epochs > max_deal_duration_epochs:
                utils.confirm_ok(
                    f"Organization {offer.organization_address} [db_id {offer.org_id}] has min deal duration of {min_deal_duration_epochs} epochs, "
                    f"which exceeds the max deal duration of {max_deal_duration_epochs} epochs. "
                    f"Cannot return offers from this organization")
                break

            for offer_miner_id in offer.miner_ids:
                # noinspection PyArgumentList
                result.append(SPRegistryOfferInput(
                    provider_id=offer_miner_id,
                    terms=SPRegistryOfferTerms(
                        min_size_bytes=0,  # TODO
                        max_size_bytes=0,  # TODO
                        min_duration_epochs=min_deal_duration_epochs,
                        max_duration_epochs=max_deal_duration_epochs
                    ),
                    slis=sla_class_to_sli_thresholds(offer.sla_class),
                    payments=payments
                ))

    if miner_id is not None and result:
        result = [offer for offer in result if offer.provider_id == miner_id]

    return result


def get_db_sps(db_url: str,
               kyc_status: str | None = None,
               organization_db_id: int | None = None,
               miner_id: ActorId | None = None,
               organization_address: str | None = None) -> list[SPRegistryProviderInput]:
    #

    result: list[SPRegistryProviderInput] = []
    organizations = SPRegistryDB(db_url).get_organizations(
        kyc_status=kyc_status,
        organization_db_id=organization_db_id,
        miner_id=miner_id,
        organization_address=organization_address)

    for org in organizations:
        if org.kyc_status.strip().lower() != "approved":
            if not utils.confirm(
                    f"Organization {org.organization_address} [db_id {org.org_id}] has kyc_status {org.kyc_status}, which is != approved. "
                    f"Return SPs from this organization?",
                    default=bool(organization_db_id)):
                continue

        try:
            if FilAddress.is_filecoin_address(org.organization_address):
                organization_address = EthAddress.from_filecoin_address(org.organization_address)

                if not utils.confirm(
                        f"Converted organization {org.organization_address} [db_id {org.org_id}] Filecoin f-address "
                        f"to EVM 0x-address {organization_address}. "
                        f"Return SPs from this organization?",
                        default=True,
                        session_id="get-db-sps"):
                    continue
            else:
                organization_address = EthAddress(org.organization_address)

        except ValueError as e:
            utils.confirm_ok(
                f"Invalid organization address {org.organization_address} [db_id {org.org_id}]: {e}. "
                f"Cannot return SPs from this organization")
            continue

        #

        for org_miner_id in org.miner_ids:
            # noinspection PyArgumentList
            result.append(SPRegistryProviderInput(
                provider_id=org_miner_id,
                organization_address=organization_address,
                available_bytes=humanfriendly.parse_size(org.capacity_commitment),
                payee_address=org.payment_address_evm
            ))

    if miner_id is not None and result:
        result = [provider for provider in result if provider.provider_id == miner_id]

    provider_ids = [sp.provider_id for sp in result]
    if len(provider_ids) != len(set(provider_ids)):
        duplicated_ids = list({provider_id for provider_id in provider_ids if provider_ids.count(provider_id) > 1})
        raise click.ClickException(f"\nDuplicated miner_id in SPRegistry database: {duplicated_ids}")

    return result


def get_mocked_sps() -> list[SPRegistryProviderInput]:
    # noinspection PyArgumentList
    return [
        SPRegistryProviderInput(provider_id=1000,
                                organization_address="0x99A1b7CE10b02b490F14B1921feCc53625c1952D",
                                available_bytes=94359739998368,
                                payee_address="0x99A1b7CE10b02b490F14B1921feCc53625c1952D"),
        SPRegistryProviderInput(provider_id=1001,
                                organization_address="0x087Ea8b72CBf4B435023356776834eB10dd07f2a",
                                available_bytes=94359739998368,
                                payee_address="0x087Ea8b72CBf4B435023356776834eB10dd07f2a"),
        SPRegistryProviderInput(provider_id=1002,
                                organization_address="0x25d4D2EC6814f9FD405a9c3e32E9b7c38358b9ED",
                                available_bytes=10 * 1024 * 1024 * 1024,
                                payee_address="0x1efBbe336C7763fB63f57d2490269A577fAbD841"),
    ]


def get_mocked_offers() -> list[SPRegistryOfferInput]:
    # TODO ASAP
    return []
