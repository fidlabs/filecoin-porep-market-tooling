import enum

from cli import utils
from cli.services.contract_service import ContractService
from cli.services.contracts.data_cap_evidence_adapter import DataCapEvidenceStatus
from cli.services.txsigner import TxSigner
from cli.services.web3_service import EthAddress, ActorId


# @notice Unified SLI thresholds for requirements, capabilities, and attestations
@utils.json_dataclass()
class PoRepMarketSLIThresholds:
    retrievability_bps: int  # Valid range: 0-10000 (basis points, e.g. 7550 = 75.50%). 0 means "don't care"
    bandwidth_bytes_per_second: int  # Capped at ~64 Gbps
    latency_ms: int
    indexing_pct: int  # Valid range: 0-100. 0 means "don't care"

    @staticmethod
    def from_web3(data) -> "PoRepMarketSLIThresholds":
        if data[0] is None:
            raise RuntimeError("SLI thresholds not found")

        # noinspection PyArgumentList
        return PoRepMarketSLIThresholds(
            retrievability_bps=int(data[0]),
            bandwidth_bytes_per_second=int(data[1]),
            latency_ms=int(data[2]),
            indexing_pct=int(data[3])
        )


# @notice DealRequest struct represents the client's request for a storage deal
# @param manifestHash commitment for piece set
# @param requestedSizeBytes requested data size in bytes
# @param maxPricePer32GiBPerMonth maximum price per 32GiB per month
# @param manifestLocation location of the deal manifest
# @param paymentToken token used for payments
# @param durationDays requested deal duration in days
# @param requiredSLIs required service-level indicators
@utils.json_dataclass()
class PoRepMarketDealRequest:
    manifest_hash: bytes
    requested_size_bytes: int
    max_price_per_32_gib_per_month: int
    manifest_location: str
    payment_token_address: EthAddress
    duration_days: int  # Client-facing input; converted once before storage
    required_slis: PoRepMarketSLIThresholds

    def __post_init__(self):
        self.payment_token_address = EthAddress(self.payment_token_address)

    @staticmethod
    def from_web3(data) -> "PoRepMarketDealRequest":
        if data[0] is None:
            raise RuntimeError("Deal request not found")

        # noinspection PyArgumentList
        return PoRepMarketDealRequest(
            manifest_hash=data[0],
            requested_size_bytes=int(data[1]),
            max_price_per_32_gib_per_month=int(data[2]),
            manifest_location=data[3],
            payment_token_address=EthAddress(data[4]),
            duration_days=int(data[5]),
            required_slis=PoRepMarketSLIThresholds.from_web3(data[6])
        )


# @title Deal State
# @notice Gapped, append-only deal lifecycle state codes.
# @dev Adapter and rail progress are represented separately from the core deal lifecycle.
class PoRepMarketDealState(enum.Enum):
    NONE = 0
    PROPOSED = 10
    ACCEPTED = 20
    ACTIVE = 30
    FINALIZED = 40
    REJECTED = 50
    EXPIRED = 60
    TERMINATED = 70

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name

    @staticmethod
    def to_string_list():
        return [state.name for state in PoRepMarketDealState]

    @staticmethod
    def from_web3(s: str | int | None) -> "PoRepMarketDealState":
        if not s:
            raise ValueError("Deal state string cannot be None")

        s = str(s).strip().lower()

        if s in ("0", "none"):
            return PoRepMarketDealState.NONE
        elif s in ("10", "proposed"):
            return PoRepMarketDealState.PROPOSED
        elif s in ("20", "accepted"):
            return PoRepMarketDealState.ACCEPTED
        elif s in ("30", "active"):
            return PoRepMarketDealState.ACTIVE
        elif s in ("40", "finalized"):
            return PoRepMarketDealState.FINALIZED
        elif s in ("50", "rejected"):
            return PoRepMarketDealState.REJECTED
        elif s in ("60", "expired"):
            return PoRepMarketDealState.EXPIRED
        elif s in ("70", "terminated"):
            return PoRepMarketDealState.TERMINATED
        else:
            raise ValueError(f"Invalid deal state: {s}")


# @notice Core deal snapshot and lifecycle fields.
@utils.json_dataclass()
class PoRepMarketDeal:
    deal_id: int
    client_address: EthAddress
    provider_id: ActorId
    offer_id: int
    state: PoRepMarketDealState
    evidence_adapter_address: EthAddress
    validator_address: EthAddress
    rail_id: int

    def __post_init__(self):
        self.provider_id = ActorId(self.provider_id)
        self.client_address = EthAddress(self.client_address)
        self.validator_address = EthAddress(self.validator_address)
        self.evidence_adapter_address = EthAddress(self.evidence_adapter_address)

    @staticmethod
    def from_web3(data, expected_deal_id: int | None = None) -> "PoRepMarketDeal":
        if data[0] is None:
            raise RuntimeError("Deal not found")

        if expected_deal_id is not None and int(data[0]) != expected_deal_id:
            raise ValueError(f"Expected deal ID {expected_deal_id}, but got {data[0]}")

        # noinspection PyArgumentList
        return PoRepMarketDeal(
            deal_id=int(data[0]),
            client_address=EthAddress(data[1]),
            provider_id=ActorId(data[2]),
            offer_id=int(data[3]),
            state=PoRepMarketDealState.from_web3(data[4]),
            evidence_adapter_address=EthAddress(data[5]),
            validator_address=EthAddress(data[6]),
            rail_id=int(data[7])
        )


# @notice DealData struct represents the data associated with a deal
# @param manifestHash commitment for piece set
# @param manifestLocation URL or path for humans/tools; contracts do not fetch or trust it.
@utils.json_dataclass()
class PoRepMarketDealData:
    manifest_hash: bytes
    manifest_location: str

    @staticmethod
    def from_web3(data) -> "PoRepMarketDealData":
        if data[0] is None:
            raise RuntimeError("Deal data not found")

        # noinspection PyArgumentList
        return PoRepMarketDealData(
            manifest_hash=data[0],
            manifest_location=data[1]
        )


# @notice Frozen size and duration terms for a deal.
@utils.json_dataclass()
class PoRepMarketDealTermsView:
    requested_size_bytes: int
    duration_epochs: int

    @staticmethod
    def from_web3(data) -> "PoRepMarketDealTermsView":
        if data[0] is None:
            raise RuntimeError("Deal terms not found")

        # noinspection PyArgumentList
        return PoRepMarketDealTermsView(
            requested_size_bytes=int(data[0]),
            duration_epochs=int(data[1])
        )


# @notice Proposal timing for expiry-related checks.
@utils.json_dataclass()
class PoRepMarketDealTiming:
    proposed_at_epoch: int
    expires_at_epoch: int

    @staticmethod
    def from_web3(data) -> "PoRepMarketDealTiming":
        if data[0] is None:
            raise RuntimeError("Deal timing not found")

        # noinspection PyArgumentList
        return PoRepMarketDealTiming(
            proposed_at_epoch=int(data[0]),
            expires_at_epoch=int(data[1])
        )


# @notice Service window established when storage activates.
@utils.json_dataclass()
class PoRepMarketDealService:
    service_start_epoch: int
    service_end_epoch: int
    early_termination_epoch: int
    min_time_between_settlements_in_epochs: int
    last_settled_epoch: int

    @staticmethod
    def from_web3(data) -> "PoRepMarketDealService":
        if data[0] is None:
            raise RuntimeError("Deal service not found")

        # noinspection PyArgumentList
        return PoRepMarketDealService(
            service_start_epoch=int(data[0]),
            service_end_epoch=int(data[1]),
            early_termination_epoch=int(data[2]),
            min_time_between_settlements_in_epochs=int(data[3]),
            last_settled_epoch=int(data[4])
        )


# @notice Capacity reserved by proposal and committed at activation.
@utils.json_dataclass()
class PoRepMarketDealCapacity:
    reserved_bytes: int
    committed_bytes: int

    @staticmethod
    def from_web3(data) -> "PoRepMarketDealCapacity":
        if data[0] is None:
            raise RuntimeError("Deal capacity not found")

        # noinspection PyArgumentList
        return PoRepMarketDealCapacity(
            reserved_bytes=int(data[0]),
            committed_bytes=int(data[1])
        )


# @notice Payment fields exposed through DealView.
@utils.json_dataclass()
class PoRepMarketDealPayment:
    payment_token: EthAddress
    price_per_32_gib_per_month: int
    billed_32_gib_units: int
    rail_max_rate_per_epoch: int

    def __post_init__(self):
        self.payment_token = EthAddress(self.payment_token)

    @staticmethod
    def from_web3(data) -> "PoRepMarketDealPayment":
        if data[0] is None:
            raise RuntimeError("Deal payment not found")

        # noinspection PyArgumentList
        return PoRepMarketDealPayment(
            payment_token=EthAddress(data[0]),
            price_per_32_gib_per_month=int(data[1]),
            billed_32_gib_units=int(data[2]),
            rail_max_rate_per_epoch=int(data[3])
        )


# @notice Complete generic read model for one PoRepMarket deal.
# @dev This is for offchain tools, oracles, CLIs, and RPC consumers that need
# PoRepMarket-owned or PoRepMarket-frozen deal facts in one bounded response.
# It is not an adapter inventory API: allocation IDs, claim IDs, raw evidence
# rows, and adapter-specific progress stay on the selected evidence adapter.
# @param deal Core deal identity, actors, state, adapter, validator, and rail ID.
# @param data Manifest hash and location stored for the deal.
# @param requiredSLIs SLI thresholds required by the client.
# @param terms Frozen size and duration terms.
# @param timing Proposal and expiry epochs.
# @param service Service start and end epochs.
# @param capacity Reserved and committed bytes.
# @param payment Frozen payment token, price, billing units, and rail ceiling.
# @param providerOrganization Organization selected for the provider at proposal time.
# @param evidenceStatus Adapter-local stored evidence status; this view does not refresh Filecoin actor state.
@utils.json_dataclass()
class PoRepMarketDealView:
    deal: PoRepMarketDeal
    data: PoRepMarketDealData
    required_slis: PoRepMarketSLIThresholds
    terms: PoRepMarketDealTermsView
    timing: PoRepMarketDealTiming
    service: PoRepMarketDealService
    capacity: PoRepMarketDealCapacity
    payment: PoRepMarketDealPayment
    provider_organization_address: EthAddress
    evidence_status: DataCapEvidenceStatus

    def _post_init__(self):
        self.provider_organization_address = EthAddress(self.provider_organization_address)

    @staticmethod
    def from_web3(data, expected_deal_id: int | None = None) -> "PoRepMarketDealView":
        if data[0][0] is None:
            raise RuntimeError("Deal view not found")

        # noinspection PyArgumentList
        return PoRepMarketDealView(
            deal=PoRepMarketDeal.from_web3(data[0], expected_deal_id),
            data=PoRepMarketDealData.from_web3(data[1]),
            required_slis=PoRepMarketSLIThresholds.from_web3(data[2]),
            terms=PoRepMarketDealTermsView.from_web3(data[3]),
            timing=PoRepMarketDealTiming.from_web3(data[4]),
            service=PoRepMarketDealService.from_web3(data[5]),
            capacity=PoRepMarketDealCapacity.from_web3(data[6]),
            payment=PoRepMarketDealPayment.from_web3(data[7]),
            provider_organization_address=EthAddress(data[8]),
            evidence_status=DataCapEvidenceStatus.from_web3(data[9])
        )


class PoRepMarket(ContractService):
    def __init__(self, contract_address: EthAddress | None = None):
        super().__init__(contract_address or utils.get_env_required("POREP_MARKET", required_type=EthAddress),
                         self.abi_dir() / "PoRepMarket.json")

    # @notice Proposes a deal
    # @param request The client deal request
    def propose_deal(self, request: PoRepMarketDealRequest, signer: TxSigner) -> str:
        slis = request.required_slis

        return self.sign_and_send_tx(
            self.contract.functions.proposeDeal((
                request.manifest_hash,
                request.requested_size_bytes,
                request.max_price_per_32_gib_per_month,
                request.manifest_location,
                request.payment_token_address,
                request.duration_days,
                (slis.retrievability_bps, slis.bandwidth_bytes_per_second, slis.latency_ms, slis.indexing_pct)
            )),
            signer)

    # @notice Gets the complete generic read model for one deal.
    # @dev External tools, oracles, CLIs, and RPC consumers use this bounded
    # snapshot when they need all PoRepMarket-owned or PoRepMarket-frozen facts for
    # one deal in a single eth_call. The evidence status is adapter-local stored
    # status and does not refresh Filecoin actor state.
    # @param dealId The id of the deal.
    # @return dealView Complete generic deal snapshot.
    def get_deal_view(self, deal_id: int) -> PoRepMarketDealView:
        return PoRepMarketDealView.from_web3(self.contract.functions.getDealView(deal_id).call(), deal_id)

    # @notice Gets a caller-sized page of complete generic deal views.
    # @dev Oracle jobs and CLI tools use this for normal batch scans. The caller
    # chooses `limit` because RPC providers and JSON-RPC clients have gas, timeout,
    # and response-size limits for eth_call.
    # @param offset Zero-based index in the creation-order deal ID list.
    # @param limit Maximum number of deal views to return.
    # @return dealViews Page of complete generic deal snapshots.
    # @return total Total number of created deal IDs at call time.
    def get_deal_views(self, offset: int, limit: int) -> list[PoRepMarketDealView]:
        return [PoRepMarketDealView.from_web3(view) for view in self.contract.functions.getDealViews(offset, limit).call()]

    # @notice Gets the number of deals created by PoRepMarket.
    # @dev Offchain tools and oracle jobs use this to size full scans and detect
    # whether new deals appeared while a scan was running.
    # @return count Total number of created deal IDs.
    def get_deal_count(self) -> int:
        return self.contract.functions.getDealCount().call()

    # @notice Gets a creation-order page of deal IDs.
    # @dev This exists for ID-first backfills, queue construction, retry logic,
    # and large oracle scans that should avoid returning nested structs and strings
    # before a worker knows which deals it needs to process. The caller chooses
    # `limit` based on RPC gas, timeout, and response-size limits.
    # @param offset Zero-based index in the creation-order deal ID list.
    # @param limit Maximum number of deal IDs to return.
    # @return dealIds Page of deal IDs in creation order.
    # @return total Total number of created deal IDs at call time.
    def get_deal_ids(self, offset: int, limit: int) -> tuple[list[int], int]:
        return self.contract.functions.getDealIds(offset, limit).call()

    # @notice Gets a page of deal IDs for one lifecycle state.
    # @dev Oracle jobs use this for recurring scans over active or finalized deals
    # without scanning every historical deal. The caller chooses `limit` based on
    # RPC gas, timeout, and response-size limits.
    # @param state Deal lifecycle state code.
    # @param offset Zero-based index in the state's deal ID list.
    # @param limit Maximum number of deal IDs to return.
    # @return dealIds Page of deal IDs in the state's existing index order.
    # @return total Total number of deal IDs in this state at call time.
    def get_deal_ids_by_state(self, state: PoRepMarketDealState, offset: int, limit: int) -> tuple[list[int], int]:
        return self.contract.functions.getDealIdsByState(state.value, offset, limit).call()

    # @notice Gets deals for a specific organization by state
    # @param organization_address The address of the organization
    # @param state The state of the deals to retrieve
    # @return deals Array of deal proposals for the organization in the specified state (from all providers associated with the organization)
    def get_deals_for_organization_by_state(self, organization_address: EthAddress, state: PoRepMarketDealState) -> list[PoRepMarketDeal]:
        return [PoRepMarketDeal.from_web3(deal) for deal in
                self.contract.functions.getDealsForOrganizationByState(organization_address, state.value).call()]

    # @notice Accepts a deal
    # @param dealId The id of the deal proposal
    def accept_deal(self, deal_id: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.acceptDeal(deal_id), signer)

    # @notice Finalizes an active deal after service has finished
    # @param dealId The id of the deal
    def finalize_deal(self, deal_id: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.finalizeDeal(deal_id), signer)

    # @notice Terminate a deal
    # @dev Terminates a deal by setting the deal state to terminated
    # @param dealId The id of the deal
    # @param endEpoch The Filecoin epoch at which the deal was terminated
    def terminate_deal(self, deal_id: int, end_epoch: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.terminateDeal(deal_id, end_epoch), signer)

    # @notice Rejects a deal
    # @param dealId The id of the deal proposal
    def reject_deal(self, deal_id: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.rejectDeal(deal_id), signer)

    # @notice Rejects a deal in Accepted state before rail is set
    # @dev Only callable by the admin
    # @param dealId The id of the deal proposal
    def reject_accepted_deal(self, deal_id: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.rejectAcceptedDeal(deal_id), signer)

    # @notice Rejects expired deal
    # @param dealId The id of the deal
    # @dev A deal is considered expired if it has been in the proposed state past the configured expiration
    def reject_expired_deal(self, deal_id: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.rejectExpiredDeal(deal_id), signer)

    # @notice Updates the rail id for a deal proposal
    # @dev Updates the rail id for a deal proposal
    # @param dealId The id of the deal proposal
    # @param railId The id of the rail
    def update_rail_id(self, deal_id: int, rail_id: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.updateRailId(deal_id, rail_id), signer)

    # @notice Maximum deal duration in days. See PoRepTypes.MAX_DEAL_DURATION_DAYS.
    # @dev Any provider limit above this is unreachable: PoRepMarket rejects deals with durationDays > 1278.
    def get_max_deal_duration_days(self) -> int:
        return self.contract.functions.MAX_DEAL_DURATION_DAYS().call()

    # @notice Number of epochs in one month
    # @dev 30 days * 24 hours/day * 60 minutes/hour * 2 epochs/minute = 86_400 epochs
    def get_epochs_in_month(self) -> int:
        return self.contract.functions.EPOCHS_IN_MONTH().call()

    # @notice Size of a single Filecoin sector in bytes (32 GiB)
    def get_sector_size_bytes(self) -> int:
        return self.contract.functions.SECTOR_SIZE().call()

    # @notice Gets the SPRegistry contract address from storage
    # @return ISPRegistry The SPRegistry contract address
    def get_sp_registry_contract_address(self) -> EthAddress:
        return self.contract.functions.getSPRegistryContract().call()

    # @notice Gets the global evidence adapter address from storage
    # @return The global evidence adapter address
    def get_global_evidence_adapter_address(self) -> EthAddress:
        return self.contract.functions.getGlobalEvidenceAdapter().call()

    # @notice Gets the validator factory contract address from storage
    # @return IValidatorFactory The validator factory contract address
    def get_validator_factory_contract_address(self) -> EthAddress:
        return self.contract.functions.getValidatorFactoryContract().call()

    # @notice Gets the evidence adapter address assigned to a deal
    # @param dealId The id of the deal
    # @return The evidence adapter address for the deal
    def get_deal_evidence_adapter_address(self, deal_id: int) -> EthAddress:
        return self.contract.functions.getDealEvidenceAdapter(deal_id).call()

    # @notice Activates an accepted deal and starts payment
    # @dev Verifies evidence, commits capacity, initializes the service window, and asks the validator to update the rail.
    # @param dealId The id of the deal
    def activate_payment(self, deal_id: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.activatePayment(deal_id), signer)

    # @notice Submit evidence to the adapter assigned to a deal
    # @param dealId The id of the deal
    # @param evidenceData Adapter-specific evidence payload
    # @return decision Adapter activation decision for the submitted batch
    def submit_evidence_batch(self, deal_id: int, evidence_data: bytes, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.submitEvidenceBatch(deal_id, evidence_data), signer)

    # @notice Activate evidence for a deal through its assigned adapter
    # @param dealId The id of the deal
    # @param evidenceData Adapter-specific evidence payload
    # @return decision Adapter activation decision
    def activate_evidence(self, deal_id: int, evidence_data: bytes, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.activateEvidence(deal_id, evidence_data), signer)

    # @notice Refresh evidence status for a deal through its assigned adapter
    # @param dealId The id of the deal
    # @param evidenceData Adapter-specific evidence payload
    # @return status Updated evidence status
    def refresh_evidence_status(self, deal_id: int, evidence_data: bytes, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.refreshEvidenceStatus(deal_id, evidence_data), signer)

    # @notice Reads current evidence status for a deal through its assigned adapter
    # @param dealId The id of the deal
    # @return status Current evidence status
    def current_evidence_status(self, deal_id: int) -> DataCapEvidenceStatus:
        return DataCapEvidenceStatus.from_web3(self.contract.functions.currentEvidenceStatus(deal_id).call())

    # @notice Updates the validator instance assigned to a deal
    # @param dealId The id of the deal
    def update_validator(self, deal_id: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.updateValidator(deal_id), signer)

    # @notice Gets the deal proposal expiration window (in epochs)
    def get_deal_expiration(self) -> int:
        return self.contract.functions.getDealExpiration().call()

    # @notice Sets a new deal proposal expiration window (in epochs)
    # @param newDealExpiration The new expiration value
    def set_new_deal_expiration(self, new_deal_expiration: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.setNewDealExpiration(new_deal_expiration), signer)

    # @notice Minimum deal duration in days. See PoRepTypes.MIN_DEAL_DURATION_DAYS.
    def get_min_deal_duration_days(self) -> int:
        return self.contract.functions.MIN_DEAL_DURATION_DAYS().call()
