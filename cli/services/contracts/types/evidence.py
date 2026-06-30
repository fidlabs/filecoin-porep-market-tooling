import enum

from cli import utils
from cli.services.web3_service import ActorId, EthAddress

class EvidenceResult(enum.Enum):
    NONE = 0
    ACCEPTED = 10
    REJECTED = 20

    @staticmethod
    def from_string(s: str | None) -> "EvidenceResult | None":
        if not s:
            return None

        s = s.strip().lower()

        if s == "none":
            return EvidenceResult.NONE
        elif s == "accepted":
            return EvidenceResult.ACCEPTED
        elif s == "rejected":
            return EvidenceResult.REJECTED
        else:
            raise ValueError(f"Invalid evidence result: {s}")

    @staticmethod
    def to_string_list():
        return [result.name for result in EvidenceResult]

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name

class EvidenceTypes(enum.Enum):
    NONE = 0
    VERIF_REG_CLAIMS = 10

    @staticmethod
    def from_string(s: str | None) -> "EvidenceTypes | None":
        if not s:
            return None

        s = s.strip().lower()

        if s == "none":
            return EvidenceTypes.NONE
        elif s == "verif_reg_claims":
            return EvidenceTypes.VERIF_REG_CLAIMS

    @staticmethod
    def to_string_list():
        return [type.name for type in EvidenceTypes]

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


# @notice ActivationContext struct represents the context for deal activation
# @param dealId ID of the deal
# @param requestedSizeBytes requested data size in bytes
# @param client address of the client
# @param durationEpochs requested deal duration in epochs
# @param activationToleranceBps activation tolerance in basis points
# @param provider ID of the provider
@utils.json_dataclass()
class ActivationContext:
    deal_id: int
    requested_size_bytes: int
    client: EthAddress
    duration_epochs: int
    activation_tolerance_bps: int
    provider: ActorId

# 
# @notice ActivationDecision struct represents the decision for deal activation
#   @param covered_bytes accepted bytes from adapter-checked allocation/claim evidence
# @param reason_code code representing the reason for the decision
# @param result activation result code
#
@utils.json_dataclass()
class ActivationDecision:
    covered_bytes: int
    reason_code: int
    result: int

# @notice EvidenceStatus struct represents the status of evidence for a deal
# @param active_covered_bytes currently active bytes from adapter-checked evidence
# @param last_evidence_refresh_epoch epoch of the last evidence refresh
# @param reason_code code representing the reason for the current status
# @param result current result code based on submitted evidence
#
@utils.json_dataclass()
class EvidenceStatus:
    active_covered_bytes: int
    last_evidence_refresh_epoch: int
    reason_code: int
    result: int


# @notice SettlementDecision struct represents the decision for deal settlement
# @param settlement_amount amount to be settled based on evidence and deal terms
# @param settle_upto_epoch epoch up to which the settlement is calculated
# @param reason_code code representing the reason for the settlement decision
# @param result settlement result code
@utils.json_dataclass()
class SettlementDecision:
    settlement_amount: int
    settle_upto_epoch: int
    reason_code: int
    result: int
