import enum
import re

from cli import utils
from cli.services.contract_service import ContractService
from cli.services.contracts.data_cap_evidence_adapter import DataCapEvidenceStatus
from cli.services.txsigner import TxSigner
from cli.services.web3_service import ActorId, EthAddress


# @notice Unified SLI thresholds for requirements, capabilities, and attestations
@utils.json_dataclass()
class PoRepMarketSLIThresholds:
    retrievability_bps: int  # Valid range: 0-10000 (basis points, e.g. 7550 = 75.50%). 0 means "don't care"
    bandwidth_bytes_per_second: int
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


# @title DealType
# @notice Shared deal type constants for PoRepMarket
class PoRepMarketDealType(enum.Enum):
    NONE = 0
    PUBLIC = 10
    PRIVATE = 20

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name

    @staticmethod
    def from_web3(s: str | int | None) -> "PoRepMarketDealType":
        if s is None or s == "":
            raise ValueError(f"Invalid deal type: {s}")

        s = str(s).strip().lower()

        if s in ("0", "none"):
            return PoRepMarketDealType.NONE
        elif s in ("10", "public"):
            return PoRepMarketDealType.PUBLIC
        elif s in ("20", "private"):
            return PoRepMarketDealType.PRIVATE
        else:
            raise ValueError(f"Invalid deal type: {s}")


# @notice DealRequest struct represents the client's request for a storage deal
# @param manifestHash commitment for piece set
# @param requestedSizeBytes requested data size in bytes
# @param maxPricePer32GiBPerMonth maximum price per 32GiB per month
# @param manifestLocation location of the deal manifest
# @param paymentToken token used for payments
# @param durationDays requested deal duration in days
# @param dealType type of deal requested
# @param requiredSLIs required service-level indicators
@utils.json_dataclass()
class PoRepMarketDealRequest:
    manifest_hash: bytes
    requested_size_bytes: int
    max_price_per_32_gib_per_month: int
    manifest_location: str
    payment_token_address: EthAddress
    duration_days: int  # Client-facing input; converted once before storage
    deal_type: PoRepMarketDealType
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
            manifest_location=re.sub(r"\s+", "", data[3]),
            payment_token_address=EthAddress(data[4]),
            duration_days=int(data[5]),
            deal_type=PoRepMarketDealType.from_web3(data[6]),
            required_slis=PoRepMarketSLIThresholds.from_web3(data[7])
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
        if s is None or s == "":
            raise ValueError(f"Invalid deal state: {s}")

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
    deal_type: PoRepMarketDealType
    validator_address: EthAddress
    rail_id: int
    proposed_at_epoch: int

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
            deal_type=PoRepMarketDealType.from_web3(data[6]),
            validator_address=EthAddress(data[7]),
            rail_id=int(data[8]),
            proposed_at_epoch=int(data[9])
        )


# @title SettlementReason
# @notice Settlement-specific reason code constants for PoRepMarket decisions
class PoRepMarketSettlementReason(enum.Enum):
    OK = 0
    DEAL_ENDED = 10
    DEAL_TERMINATED = 20
    TOO_EARLY = 30
    SCORE_BELOW_THRESHOLD = 40
    DATA_SIZE_MISMATCH = 50
    EVIDENCE_TOO_STALE = 60

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name

    @staticmethod
    def from_web3(s: str | int | None) -> "PoRepMarketSettlementReason":
        if s is None or s == "":
            raise ValueError(f"Invalid settlement reason: {s}")

        s = str(s).strip().lower()

        if s in ("0", "ok"):
            return PoRepMarketSettlementReason.OK
        elif s in ("10", "deal_ended"):
            return PoRepMarketSettlementReason.DEAL_ENDED
        elif s in ("20", "deal_terminated"):
            return PoRepMarketSettlementReason.DEAL_TERMINATED
        elif s in ("30", "too_early"):
            return PoRepMarketSettlementReason.TOO_EARLY
        elif s in ("40", "score_below_threshold"):
            return PoRepMarketSettlementReason.SCORE_BELOW_THRESHOLD
        elif s in ("50", "data_size_mismatch"):
            return PoRepMarketSettlementReason.DATA_SIZE_MISMATCH
        elif s in ("60", "evidence_too_stale"):
            return PoRepMarketSettlementReason.EVIDENCE_TOO_STALE
        else:
            raise ValueError(f"Invalid settlement reason: {s}")


# @title SettlementResult
# @notice Settlement-specific result constants for PoRepMarket decisions
class PoRepMarketSettlementResult(enum.Enum):
    NONE = 0
    ACCEPTED = 10
    MODIFIED = 20
    REJECTED = 30

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name

    @staticmethod
    def from_web3(s: str | int | None) -> "PoRepMarketSettlementResult":
        if s is None or s == "":
            raise ValueError(f"Invalid settlement result: {s}")

        s = str(s).strip().lower()

        if s in ("0", "none"):
            return PoRepMarketSettlementResult.NONE
        elif s in ("10", "accepted"):
            return PoRepMarketSettlementResult.ACCEPTED
        elif s in ("20", "modified"):
            return PoRepMarketSettlementResult.MODIFIED
        elif s in ("30", "rejected"):
            return PoRepMarketSettlementResult.REJECTED
        else:
            raise ValueError(f"Invalid settlement result: {s}")


# @notice SettlementDecision struct represents the decision for deal settlement
# @param settlementAmount amount to be settled based on evidence and deal terms
# @param settleUpto epoch up to which the settlement is calculated
# @param reasonCode code representing the reason for the settlement decision
# @param result settlement result code
@utils.json_dataclass()
class PoRepMarketSettlementDecision:
    settlement_amount: int
    settle_upto: int
    reason_code: PoRepMarketSettlementReason
    result: PoRepMarketSettlementResult
    note: str

    @staticmethod
    def from_web3(data) -> "PoRepMarketSettlementDecision":
        if data[0] is None:
            raise RuntimeError("Settlement decision not found")

        # noinspection PyArgumentList
        return PoRepMarketSettlementDecision(
            settlement_amount=int(data[0]),
            settle_upto=int(data[1]),
            reason_code=PoRepMarketSettlementReason.from_web3(data[2]),
            result=PoRepMarketSettlementResult.from_web3(data[3]),
            note=data[4]
        )


class PoRepMarket(ContractService):
    _POREP_MARKET_ADDRESS: EthAddress | None = None

    def __init__(self, contract_address: EthAddress | None = None):
        if not contract_address and not PoRepMarket._POREP_MARKET_ADDRESS:
            from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper
            PoRepMarket._POREP_MARKET_ADDRESS = PoRepMarketViewHelper().porep_market_contract()

        # noinspection PyTypeChecker
        super().__init__(contract_address or PoRepMarket._POREP_MARKET_ADDRESS,
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
                request.deal_type,
                (slis.retrievability_bps, slis.bandwidth_bytes_per_second, slis.latency_ms, slis.indexing_pct)
            )),
            signer
        )

    # @notice Proposes a deal against a specific provider offer
    # @dev Only admins can bypass automatic matching and reserve a specific offer
    # @param offerId The provider offer to reserve for the deal
    # @param request The client deal request
    def propose_deal_with_specific_offer(self, offer_id: int, request: PoRepMarketDealRequest, signer: TxSigner) -> str:
        slis = request.required_slis

        return self.sign_and_send_tx(
            self.contract.functions.proposeDealWithSpecificOffer(offer_id, (
                request.manifest_hash,
                request.requested_size_bytes,
                request.max_price_per_32_gib_per_month,
                request.manifest_location,
                request.payment_token_address,
                request.duration_days,
                request.deal_type,
                (slis.retrievability_bps, slis.bandwidth_bytes_per_second, slis.latency_ms, slis.indexing_pct)
            )),
            signer
        )

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

    # @notice Gets all deals
    # @return deals Array of all deals
    def get_deals(self) -> list[PoRepMarketDeal]:
        return [PoRepMarketDeal.from_web3(deal) for deal in self.contract.functions.getDeals().call()]

    # @notice Accepts a deal
    # @param dealId The id of the deal proposal
    def accept_deal(self, deal_id: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.acceptDeal(deal_id), signer)

    # @notice Finalizes an active deal after service has finished
    # @param dealId The id of the deal
    def finalize_deal(self, deal_id: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.finalizeDeal(deal_id), signer)

    # @notice Terminates a deal with the requested terminal state
    # @param dealId The id of the deal
    # @param state The terminal state to assign to the deal
    def terminate_deal(self, deal_id: int, state: PoRepMarketDealState, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.terminateDeal(deal_id, state.value), signer)

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

    # @notice Minimum Filecoin deal duration equals 180 days (6 months)
    def get_min_deal_duration_days(self) -> int:
        return self.contract.functions.MIN_DEAL_DURATION_DAYS().call()

    # @notice Number of epochs in one month
    # @dev 30 days * 24 hours/day * 60 minutes/hour * 2 epochs/minute = 86_400 epochs
    def get_epochs_in_month(self) -> int:
        return self.contract.functions.EPOCHS_IN_MONTH().call()

    # @notice Size of a single Filecoin sector in bytes (32 GiB)
    def get_sector_size_bytes(self) -> int:
        return self.contract.functions.SECTOR_SIZE().call()

    # @notice Gets the deal activation padding (in percent)
    def get_deal_activation_padding(self) -> int:
        return self.contract.functions.getDealActivationPadding().call()

    # @notice Sets the deal activation padding (in percent)
    # @dev Only callable by the admin
    def set_deal_activation_padding(self, padding: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.setDealActivationPadding(padding), signer)

    # @notice Sets the minimum time between settlements for a deal
    # @dev Only the admin may update the settlement cadence.
    # @param dealId The deal being configured
    # @param minEpochs Minimum time between settlements in epochs
    def set_min_epochs_between_settlements(self, deal_id: int, min_epochs: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.setMinEpochsBetweenSettlements(deal_id, min_epochs), signer)

    # @notice Validates the settlement amount for a deal's service window
    # @dev Only the deal's validator may request a settlement decision. settleUpto controls how far FilecoinPay may
    # advance its cursor, including for rejected zero-payment windows.
    # @param dealId The deal being settled
    # @param fromEpoch The epoch at which the settlement window starts
    # @param toEpoch The epoch at which the settlement window ends
    # @return decision The amount and epoch accepted for settlement
    def validate_deal_settlement(self, deal_id: int, from_epoch: int, to_epoch: int) -> PoRepMarketSettlementDecision:
        return PoRepMarketSettlementDecision.from_web3(self.contract.functions.validateDealSettlement(deal_id, from_epoch, to_epoch).call())

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

    # @notice Updates the manifest location for a specific deal
    # @dev Only callable by the admin
    # @param dealId The unique identifier of the deal
    # @param newManifestLocation The new manifest location URL to be updated for the deal
    def update_manifest_location(self, deal_id: int, new_manifest_location: str, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.updateManifestLocation(deal_id, new_manifest_location), signer)

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
