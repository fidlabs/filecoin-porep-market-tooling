from datetime import datetime

import psycopg

from cli import utils
from cli.services.web3_service import EthAddress, ActorId


@utils.json_dataclass()
class SPRegistryDBSLAClass:
    sla_id: int
    provider_id: int
    sla_class: str
    price_per_tib_usd: float
    specific_miner_id: ActorId | None
    regional_pricing: list[dict]

    # created_at: datetime
    # updated_at: datetime

    @staticmethod
    def from_db(data) -> "SPRegistryDBSLAClass":
        # noinspection PyArgumentList
        return SPRegistryDBSLAClass(
            sla_id=int(data[0]),
            provider_id=int(data[1]),
            sla_class=data[2],
            price_per_tib_usd=float(data[3]),
            specific_miner_id=ActorId(data[4]) if data[4] is not None else None,
            regional_pricing=data[5],
            # created_at=data[6],
            # updated_at=data[7]
        )


@utils.json_dataclass()
class SPRegistryDBOrganization:
    org_id: int
    name: str
    miner_ids: list[ActorId]
    accepted_client_geographies: list[str]
    payment_types: list[str]
    retrievability_guarantees: list[str]
    bandwidth_tier: list[str]
    service_frequency: list[str]
    data_types: list[str]
    customer_support_email: str
    contact_details: str
    onboarding_bandwidth: str
    payment_address: str
    organization_address: str
    kyc_session_id: str | None
    kyc_session_url: str | None
    kyc_status: str
    kyc_completed_at: datetime | None
    # created_at: datetime
    # updated_at: datetime
    geographical_location: list[str]
    kyc_email: str
    payment_address_evm: EthAddress
    deal_duration_min_months: int
    deal_duration_max_months: int
    min_price_per_tib_usd: float
    sp_software: list[str]
    capacity_commitment: str
    controller_address: str | None = None
    manage_token: str | None = None
    manage_token_expires_at: datetime | None = None

    @staticmethod
    def from_db(data) -> "SPRegistryDBOrganization":
        miner_ids = [ActorId(miner_id) for miner_id in data[2]]

        if any(miner_id is None for miner_id in miner_ids):
            raise ValueError(f"Invalid miner ID in database for db_id {data[0]}: {data[2]}")

        # noinspection PyArgumentList
        return SPRegistryDBOrganization(
            org_id=int(data[0]),
            name=data[1],
            miner_ids=miner_ids,
            accepted_client_geographies=data[3],
            payment_types=data[4],
            retrievability_guarantees=data[5],
            bandwidth_tier=data[6],
            service_frequency=data[7],
            data_types=data[8],
            customer_support_email=data[9],
            contact_details=data[10],
            onboarding_bandwidth=data[11],
            payment_address=data[12],
            organization_address=data[13],
            kyc_session_id=data[14],
            kyc_session_url=data[15],
            kyc_status=data[16],
            kyc_completed_at=data[17],
            # created_at=data[18],
            # updated_at=data[19],
            geographical_location=data[20],
            kyc_email=data[21],
            payment_address_evm=EthAddress(data[22]),
            deal_duration_min_months=int(data[23]),
            deal_duration_max_months=int(data[24]),
            min_price_per_tib_usd=float(data[25]),
            sp_software=data[26],
            capacity_commitment=data[27],
            controller_address=data[28],
            manage_token=data[29],
            manage_token_expires_at=data[30]
        )


@utils.json_dataclass()
class SPRegistryDBSLAClassJoinOrganization(SPRegistryDBOrganization, SPRegistryDBSLAClass):
    @staticmethod
    def from_db(data) -> "SPRegistryDBSLAClassJoinOrganization":
        # noinspection PyArgumentList
        return SPRegistryDBSLAClassJoinOrganization(
            **SPRegistryDBOrganization.from_db(data[:31]).__dict__,
            **SPRegistryDBSLAClass.from_db(data[31:]).__dict__
        )


class SPRegistryDB:
    def __init__(self, db_url: str):
        self.db_url = db_url

    def get_sla_classes(self,
                        kyc_status: str | None = None,
                        organization_id: int | None = None,
                        miner_id: ActorId | None = None,
                        organization_address: str | None = None) -> list[SPRegistryDBSLAClassJoinOrganization]:
        #
        query = """SELECT providers.*, provider_sla_classes.*
                   FROM provider_sla_classes
                            JOIN providers ON provider_sla_classes.provider_id = providers.id
                   WHERE true"""

        params = []

        if organization_address is not None:
            query += " AND lower(providers.organization_address) = lower(%s)"
            params.append(organization_address)

        if kyc_status is not None:
            query += " AND lower(providers.kyc_status) = lower(%s)"
            params.append(kyc_status)

        if organization_id is not None:
            query += " AND providers.id = %s"
            params.append(organization_id)

        if miner_id is not None:
            query += " AND %s = ANY(providers.miner_ids)"
            params.append(str(miner_id))

        with psycopg.connect(self.db_url) as conn:
            # noinspection PyTypeChecker
            result = [
                SPRegistryDBSLAClassJoinOrganization.from_db(r)
                for r in conn.execute(query, params).fetchall()
            ]

        return result

    def get_organizations(self,
                          kyc_status: str | None = None,
                          organization_db_id: int | None = None,
                          miner_id: ActorId | None = None,
                          organization_address: str | None = None) -> list[SPRegistryDBOrganization]:
        #
        query = "SELECT * FROM providers WHERE true"
        params = []

        if organization_address is not None:
            query += " AND lower(organization_address) = lower(%s)"
            params.append(organization_address)

        if kyc_status is not None:
            query += " AND lower(kyc_status) = lower(%s)"
            params.append(kyc_status)

        if organization_db_id is not None:
            query += " AND id = %s"
            params.append(organization_db_id)

        if miner_id is not None:
            query += " AND %s = ANY(miner_ids)"
            params.append(str(miner_id))

        with psycopg.connect(self.db_url) as conn:
            # noinspection PyTypeChecker
            result = [
                SPRegistryDBOrganization.from_db(r)
                for r in conn.execute(query, params).fetchall()
            ]

        return result
