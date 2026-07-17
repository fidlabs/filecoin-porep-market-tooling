import click
import humanfriendly

from cli import utils
from cli.services.contracts.erc20_contract import ERC20Contract
from cli.services.contracts.porep_market import PoRepMarket, PoRepMarketSLIThresholds
from cli.services.contracts.sp_registry import SPRegistryProviderInput, SPRegistryOfferInput, SPRegistryOfferTerms, SPRegistryOfferPaymentInput
from cli.services.contracts.usdc_token import USDCToken
from cli.services.sp_registry_db import SPRegistryDB
from cli.services.web3_service import EthAddress, ActorId, FilAddress


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

    #  deprecated porep v1:

    # def retrievability_guarantees_to_bps(guarantees: list[str]) -> int:
    #     def _retrievability_guarantee_to_bps(guarantee: str) -> int:
    #         DECIMALS = 2
    #         DECIMALS_MULTIPLIER = 10 ** DECIMALS
    #
    #         if guarantee == "hot":
    #             return 90 * DECIMALS_MULTIPLIER  # 90 %
    #         elif guarantee == "sometimes":
    #             return 75 * DECIMALS_MULTIPLIER  # 75 %
    #         elif guarantee == "rarely":
    #             return 0 * DECIMALS_MULTIPLIER  # 0 %
    #         else:
    #             raise ValueError(f"Unknown retrievability guarantee: {guarantee}")
    #
    #     return max([_retrievability_guarantee_to_bps(g) for g in guarantees]) if guarantees else 0
    #
    # def bandwidth_tiers_to_bytes_per_second(tiers: list[str]) -> int:
    #     def _bandwidth_tier_to_bytes_per_second(tier: str) -> int:
    #         if tier == "fast":
    #             return 1000 * 1024 * 1024 // 8  # 1 Gbps
    #         elif tier == "normal":
    #             return 300 * 1024 * 1024 // 8  # 300 Mbps
    #         elif tier == "slow":
    #             return 1 * 1024 * 1024 // 8  # 1 Mbps
    #         else:
    #             raise ValueError(f"Unknown bandwidth tier: {tier}")
    #
    #     return max([_bandwidth_tier_to_bytes_per_second(tier) for tier in tiers]) if tiers else 0
    #
    # def retrievability_guarantees_to_latency_ms(guarantees: list[str]) -> int:
    #     def _retrievability_guarantee_to_latency_ms(guarantee: str) -> int:
    #         if guarantee == "hot":
    #             return 20 * 1000  # 20 seconds
    #         elif guarantee == "sometimes":
    #             return 20 * 1000  # 20 seconds
    #         elif guarantee == "rarely":
    #             return 24 * 60 * 60 * 1000  # 24 hours
    #         else:
    #             raise ValueError(f"Unknown retrievability guarantee: {guarantee}")
    #
    #     return min([_retrievability_guarantee_to_latency_ms(g) for g in guarantees]) if guarantees else 0

    def sla_class_to_sli_thresholds(sla_class: str) -> PoRepMarketSLIThresholds:
        sla_class = sla_class.lower()

        if sla_class == "accessible_storage":
            # noinspection PyArgumentList
            return PoRepMarketSLIThresholds(
                retrievability_bps=8000,  # 80 %
                bandwidth_bytes_per_second=322122547,  # 300 MiB per second
                latency_ms=0,  # TODO
                indexing_pct=100
            )

        elif sla_class == "premium_storage":
            # noinspection PyArgumentList
            return PoRepMarketSLIThresholds(
                retrievability_bps=10000,  # 100 %
                bandwidth_bytes_per_second=1073741824,  # 1 GiB per second
                latency_ms=0,  # TODO
                indexing_pct=100
            )

        elif sla_class == "archival":
            # TODO
            # noinspection PyArgumentList
            return PoRepMarketSLIThresholds(
                retrievability_bps=0,  # 0 %
                bandwidth_bytes_per_second=0,
                latency_ms=999,
                indexing_pct=0
            )

        if sla_class == "accessible_backup":
            # TODO
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
    MIN_DEAL_DURATION_DAYS_LIMIT = months_to_days(6)  # TODO LATER get minimum deal duration from smart contracts
    result: list[SPRegistryOfferInput] = []
    offers = SPRegistryDB(db_url).get_sla_classes(kyc_status=kyc_status,
                                                  organization_id=organization_db_id,
                                                  miner_id=miner_id,
                                                  organization_address=organization_address)

    for offer in offers:
        if offer.specific_miner_id:
            # TODO support SLA Class with specific miner_id
            utils.confirm_ok("SLA Class with non-null specific_miner_id is not supported yet. Cannot return offers from this SLA Class.")
            continue

        if offer.kyc_status.strip().lower() != "approved":
            if not utils.confirm(
                    f"Organization {offer.organization_address} [db_id {offer.org_id}] has kyc_status {offer.kyc_status}, which is != approved. "
                    f"Return SPs from this organization?",
                    default=bool(organization_db_id)):
                continue

        if months_to_days(offer.deal_duration_min_months) < MIN_DEAL_DURATION_DAYS_LIMIT:
            min_deal_duration_epochs = days_to_epochs(MIN_DEAL_DURATION_DAYS_LIMIT)

            if not utils.confirm(
                    f"Organization {offer.organization_address} [db_id {offer.org_id}] has min deal duration "
                    f"of {months_to_days(offer.deal_duration_min_months)} days which is below the SPRegistry contract minimum "
                    f"of {MIN_DEAL_DURATION_DAYS_LIMIT} days. It will be increased to this value. "
                    f"Return SPs from this organization?",
                    default=True,
                    session_id="get-db-offers"):
                continue
        else:
            min_deal_duration_epochs = months_to_epochs(offer.deal_duration_min_months)

        if months_to_days(offer.deal_duration_max_months) > MAX_DEAL_DURATION_DAYS_LIMIT:
            max_deal_duration_epochs = days_to_epochs(MAX_DEAL_DURATION_DAYS_LIMIT)

            if not utils.confirm(
                    f"Organization {offer.organization_address} [db_id {offer.org_id}] has max deal duration "
                    f"of {months_to_days(offer.deal_duration_max_months)} days which exceeds the SPRegistry contract limit "
                    f"of {MAX_DEAL_DURATION_DAYS_LIMIT} days. It will be truncated to this value. "
                    f"Return SPs from this organization?",
                    default=True,
                    session_id="get-db-offers"):
                continue
        else:
            max_deal_duration_epochs = months_to_epochs(offer.deal_duration_max_months)

        if min_deal_duration_epochs > max_deal_duration_epochs:
            utils.confirm_ok(
                f"Organization {offer.organization_address} [db_id {offer.org_id}] has min deal duration of {min_deal_duration_epochs} epochs, "
                f"which exceeds the max deal duration of {max_deal_duration_epochs} epochs. "
                f"Cannot return SPs from this organization")
            continue

        try:
            payments = [payment_type_to_payment_input(payment_type, offer.price_per_tib_usd) for payment_type in offer.payment_types]
        except ValueError as e:
            # e.g. a payment type whose token is not deployed on the connected network (devnet)
            utils.confirm_ok(f"Organization {offer.organization_address} [db_id {offer.org_id}] "
                             f"has an unsupported payment configuration: {e}\n"
                             f"Cannot return offers from this SLA Class")
            continue

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

    return result


def get_db_sps(db_url: str,
               kyc_status: str | None = None,
               organization_db_id: int | None = None,
               miner_id: ActorId | None = None,
               organization_address: str | None = None) -> list[SPRegistryProviderInput]:
    #

    result: list[SPRegistryProviderInput] = []
    organizations = SPRegistryDB(db_url).get_organizations(kyc_status=kyc_status,
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

        if FilAddress.is_filecoin_address(org.organization_address):
            try:
                organization_address = EthAddress.from_filecoin_address(org.organization_address)
            except RuntimeError as e:
                # e.g. a mainnet f-address that is not instantiated on the connected network (devnet)
                utils.confirm_ok(f"Cannot convert organization {org.organization_address} [db_id {org.org_id}] Filecoin f-address "
                                 f"to EVM 0x-address on this network: {e}\n"
                                 f"Cannot return SPs from this organization")
                continue

            if not utils.confirm(f"Converted organization {org.organization_address} [db_id {org.org_id}] Filecoin f-address "
                                 f"to EVM 0x-address {organization_address}. "
                                 f"Return SPs from this organization?",
                                 default=True,
                                 session_id="get-db-sps"):
                continue
        else:
            organization_address = org.organization_address

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
        result = [sp for sp in result if sp.provider_id == miner_id]

    provider_ids = [sp.provider_id for sp in result]
    if len(provider_ids) != len(set(provider_ids)):
        duplicated_ids = list(set([provider_id for provider_id in provider_ids if provider_ids.count(provider_id) > 1]))
        raise click.ClickException(f"\nDuplicated miner_id in SPRegistry database: {duplicated_ids}")

    return result


def get_devnet_sps() -> list[SPRegistryProviderInput]:
    # noinspection PyArgumentList
    return [
        SPRegistryProviderInput(provider_id=1000,
                                organization_address="0x62c671c2f1A89916DD0F550E5EB2318e9Aeb59b7",
                                available_bytes=94359739998368,
                                payee_address="0x99f063C701a97545B760aD6C2F7F5401850C9F11"),
        SPRegistryProviderInput(provider_id=1001,
                                organization_address="0x62c671c2f1A89916DD0F550E5EB2318e9Aeb59b7",
                                available_bytes=94359739998368,
                                payee_address="0x62c671c2f1A89916DD0F550E5EB2318e9Aeb59b7"),
        SPRegistryProviderInput(provider_id=1002,
                                organization_address="0x62c671c2f1A89916DD0F550E5EB2318e9Aeb59b7",
                                available_bytes=10 * 1024 * 1024 * 1024,
                                payee_address="0x62c671c2f1A89916DD0F550E5EB2318e9Aeb59b7"),
    ]


def get_devnet_offers() -> list[SPRegistryOfferInput]:
    # TODO
    return []
