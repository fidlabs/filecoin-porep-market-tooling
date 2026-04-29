from datetime import datetime

import psycopg

from cli import utils
from cli.services.web3_service import Address, ActorId


@utils.json_dataclass()
class SPRegistryDBOrganization:
    id: int
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
    created_at: datetime
    updated_at: datetime
    geographical_location: list[str]
    kyc_email: str
    payment_address_evm: Address
    deal_duration_min_months: int
    deal_duration_max_months: int
    min_price_per_tib_usd: float
    sp_software: list[str]
    capacity_commitment: str

    @staticmethod
    def from_db(data) -> "SPRegistryDBOrganization":
        miner_ids = [ActorId(miner_id) for miner_id in data[2]]
        db_id = int(data[0])

        if any(miner_id is None for miner_id in miner_ids):
            raise ValueError(f"Invalid miner id in database for db_id {db_id}: {data[2]}")

        # noinspection PyArgumentList
        return SPRegistryDBOrganization(
            id=db_id,
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
            created_at=data[18],
            updated_at=data[19],
            geographical_location=data[20],
            kyc_email=data[21],
            payment_address_evm=Address(data[22]),
            deal_duration_min_months=int(data[23]),
            deal_duration_max_months=int(data[24]),
            min_price_per_tib_usd=float(data[25]),
            sp_software=data[26],
            capacity_commitment=data[27],
        )


class SPRegistryDB:
    def __init__(self, db_url: str):
        self.db_url = db_url

    def get_organizations(self,
                          kyc_status: str | None = None,
                          organization_id: int | None = None,
                          miner_id: ActorId | None = None,
                          organization_address: str | None = None) -> list[SPRegistryDBOrganization]:
        #
        # this is confusing but organizations are called providers in the SPRegistry database
        # and the database miner_ids and considered provider_ids in PoRep Market smart contracts

        query = "SELECT * FROM providers WHERE true"
        params = []

        if organization_address is not None:
            query += " AND lower(organization_address) = lower(%s)"
            params.append(organization_address)

        if kyc_status is not None:
            query += " AND lower(kyc_status) = lower(%s)"
            params.append(kyc_status)

        if organization_id is not None:
            query += " AND id = %s"
            params.append(organization_id)

        if miner_id is not None:
            _miner_id = ActorId(miner_id)
            query += " AND %s = ANY(miner_ids)"
            params.append(_miner_id)

        with psycopg.connect(self.db_url) as conn:
            # noinspection PyTypeChecker
            providers = [
                SPRegistryDBOrganization.from_db(p)
                for p in conn.execute(query, params).fetchall()
            ]

        return providers
