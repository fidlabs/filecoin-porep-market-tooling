import enum

from cli import utils
from cli.services.contracts.types.evidence import EvidenceStatus
from cli.services.contracts.types.sli import SLIThresholds
from cli.services.web3_service import ActorId, EthAddress


class PoRepMarketDealState(enum.IntEnum):
    NONE = 0
    PROPOSED = 10
    ACCEPTED = 20
    ACTIVE = 30
    FINALIZED = 40
    REJECTED = 50
    EXPIRED = 60
    TERMINATED = 70

    @staticmethod
    def from_string(s: str | None) -> "PoRepMarketDealState | None":
        if not s:
            return None

        s = s.strip().lower()

        if s == "none":
            return PoRepMarketDealState.NONE
        elif s == "proposed":
            return PoRepMarketDealState.PROPOSED
        elif s == "accepted":
            return PoRepMarketDealState.ACCEPTED
        elif s == "active":
            return PoRepMarketDealState.ACTIVE
        elif s == "finalized":
            return PoRepMarketDealState.FINALIZED
        elif s == "rejected":
            return PoRepMarketDealState.REJECTED
        elif s == "expired":
            return PoRepMarketDealState.EXPIRED
        elif s == "terminated":
            return PoRepMarketDealState.TERMINATED
        else:
            raise ValueError(f"Invalid deal state: {s}")

    @staticmethod
    def to_string_list():
        return [state.name for state in PoRepMarketDealState]

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


@utils.json_dataclass()
class PoRepMarketDealTerms:
    deal_size_bytes: int
    price_per_sector_per_month: int  # Monthly price per 32 GiB sector in USDC smallest units (wei-equivalent)
    duration_days: int  # Must be divisible by 30


@utils.json_dataclass()
class PoRepMarketDealRequest:
    manifest_hash: bytes
    requested_size_bytes: int
    max_price_per_32_gib_per_month: int
    manifest_location: str
    payment_token: EthAddress
    duration_days: int
    required_slis: SLIThresholds


# @dev Represents a proposal for a PoRep deal, including all relevant details and terms
# @param deal_id: Unique identifier for the deal
# @param client_address: Address of the client proposing the deal
# @param provider_id: FilActor ID of the storage provider
# @param validator: Address of the validator responsible for validating the deal
# @param state: Current state of the deal (Proposed, Accepted, Completed, Rejected, Terminated)
# @param rail_id: ID of the payment rail associated with the deal
@utils.json_dataclass()
class PoRepMarketDeal():
    deal_id: int
    client_address: EthAddress
    provider_id: ActorId
    offer_id: int
    state: PoRepMarketDealState
    evidence_adapter_address: EthAddress
    validator_address: EthAddress
    rail_id: int

    def __post_init__(self):
        self.client_address = EthAddress(self.client_address)
        self.evidence_adapter_address = EthAddress(self.evidence_adapter_address)
        self.validator_address = EthAddress(self.validator_address)
        self.provider_id = ActorId(self.provider_id)

    @staticmethod
    def from_web3(data, expected_deal_id: int | None = None) -> "PoRepMarketDeal":
        if not EthAddress(data[1]):
            raise RuntimeError("Deal not found")

        if expected_deal_id is not None and expected_deal_id != data[0]:
            raise RuntimeError(f"Invalid deal proposal returned from contract. Expected deal_id {expected_deal_id}, got {data[0]}")

        # noinspection PyArgumentList
        return PoRepMarketDeal(
            deal_id=int(data[0]),
            client_address=EthAddress(data[1]),
            provider_id=ActorId(data[2]),
            offer_id=int(data[3]),
            state=PoRepMarketDealState(data[4]),
            evidence_adapter_address=EthAddress(data[5]),
            validator_address=EthAddress(data[6]),
            rail_id=int(data[7]),
        )

@utils.json_dataclass()
class PoRepMarketDealTermsView:
    requested_size_bytes: int
    duration_epochs: int

    @staticmethod
    def from_web3(data) -> "PoRepMarketDealTermsView":
        return PoRepMarketDealTermsView(requested_size_bytes=int(data[0]), duration_epochs=int(data[1]))


@utils.json_dataclass()
class PoRepMarketDealTiming:
    proposed_at_epoch: int
    expires_at_epoch: int

    @staticmethod
    def from_web3(data) -> "PoRepMarketDealTiming":
        return PoRepMarketDealTiming(proposed_at_epoch=int(data[0]), expires_at_epoch=int(data[1]))


@utils.json_dataclass()
class PoRepMarketDealService:
    service_start_epoch: int
    service_end_epoch: int

    @staticmethod
    def from_web3(data) -> "PoRepMarketDealService":
        return PoRepMarketDealService(service_start_epoch=int(data[0]), service_end_epoch=int(data[1]))


@utils.json_dataclass()
class PoRepMarketDealCapacity:
    reserved_bytes: int
    committed_bytes: int

    @staticmethod
    def from_web3(data) -> "PoRepMarketDealCapacity":
        return PoRepMarketDealCapacity(reserved_bytes=int(data[0]), committed_bytes=int(data[1]))


@utils.json_dataclass()
class PoRepMarketDealPayment:
    payment_token: EthAddress
    payee: EthAddress
    price_per_32_gib_per_month: int
    billed_32_gib_units: int
    rail_max_rate_per_epoch: int

    @staticmethod
    def from_web3(data) -> "PoRepMarketDealPayment":
        return PoRepMarketDealPayment(
            payment_token=EthAddress(data[0]),
            payee=EthAddress(data[1]),
            price_per_32_gib_per_month=int(data[2]),
            billed_32_gib_units=int(data[3]),
            rail_max_rate_per_epoch=int(data[4])
        )


@utils.json_dataclass()
class PoRepMarketDealData:
    manifest_hash: bytes
    manifest_location: str

    @staticmethod
    def from_web3(data) -> "PoRepMarketDealData":
        return PoRepMarketDealData(manifest_hash=bytes(data[0]), manifest_location=data[1])

# @notice Commercial terms for a deal (not Oracle-measured)
@utils.json_dataclass()
class DealTerms:
    deal_size_bytes: int
    price_per_sector_per_month: int  # Monthly price per 32 GiB sector in USDFC smallest units (wei-equivalent)
    duration_days: int

# @notice Payment fields exposed through DealView (no payee, unlike DealPayment)
@utils.json_dataclass()
class PoRepMarketDealViewPayment:
    payment_token: EthAddress
    price_per_32_gib_per_month: int
    billed_32_gib_units: int
    rail_max_rate_per_epoch: int

    @staticmethod
    def from_web3(data) -> "PoRepMarketDealViewPayment":
        return PoRepMarketDealViewPayment(
            payment_token=EthAddress(data[0]),
            price_per_32_gib_per_month=int(data[1]),
            billed_32_gib_units=int(data[2]),
            rail_max_rate_per_epoch=int(data[3])
        )


# @notice Complete generic read model for one PoRepMarket deal (getDealView)
# @param deal Core deal identity, actors, state, adapter, validator, and rail ID
# @param data Manifest hash and location stored for the deal
# @param required_slis SLI thresholds required by the client
# @param terms Frozen size and duration terms
# @param timing Proposal and expiry epochs
# @param service Service start and end epochs
# @param capacity Reserved and committed bytes
# @param payment Frozen payment token, price, billing units, and rail ceiling
# @param provider_organization Organization selected for the provider at proposal time
# @param evidence_status Adapter-local stored evidence status (not refreshed from Filecoin actor state)
@utils.json_dataclass()
class PoRepMarketDealView:
    deal: PoRepMarketDeal
    data: PoRepMarketDealData
    required_slis: SLIThresholds
    terms: PoRepMarketDealTermsView
    timing: PoRepMarketDealTiming
    service: PoRepMarketDealService
    capacity: PoRepMarketDealCapacity
    payment: PoRepMarketDealViewPayment
    provider_organization: EthAddress
    evidence_status: EvidenceStatus

    @staticmethod
    def from_web3(data, expected_deal_id: int | None = None) -> "PoRepMarketDealView":
        slis = data[2]
        status = data[9]

        return PoRepMarketDealView(
            deal=PoRepMarketDeal.from_web3(data[0], expected_deal_id=expected_deal_id),
            data=PoRepMarketDealData.from_web3(data[1]),
            required_slis=SLIThresholds(
                retrievability_bps=int(slis[0]),
                bandwidth_bytes_per_second=int(slis[1]),
                latency_ms=int(slis[2]),
                indexing_pct=int(slis[3])
            ),
            terms=PoRepMarketDealTermsView.from_web3(data[3]),
            timing=PoRepMarketDealTiming.from_web3(data[4]),
            service=PoRepMarketDealService.from_web3(data[5]),
            capacity=PoRepMarketDealCapacity.from_web3(data[6]),
            payment=PoRepMarketDealViewPayment.from_web3(data[7]),
            provider_organization=EthAddress(data[8]),
            evidence_status=EvidenceStatus(
                active_covered_bytes=int(status[0]),
                last_evidence_refresh_epoch=int(status[1]),
                reason_code=int(status[2]),
                result=int(status[3])
            )
        )