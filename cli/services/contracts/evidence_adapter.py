import enum

from cli import utils
from cli.services.contract_service import ContractService
from cli.services.web3_service import EthAddress


# @title EvidenceTypes
# @notice Shared evidence type constants for PoRepMarket
class EvidenceType(enum.Enum):
    NONE = 0
    VERIF_REG_CLAIMS = 10
    SECTOR_PLACEMENT = 20

    @staticmethod
    def from_web3(s: str | int | None) -> "EvidenceType":
        if s is None or s == "":
            raise ValueError(f"Invalid evidence type: {s}")

        s = str(s).strip().lower()

        if s in ("0", "none"):
            return EvidenceType.NONE
        elif s in ("10", "verif_reg_claims"):
            return EvidenceType.VERIF_REG_CLAIMS
        elif s in ("20", "sector_placement"):
            return EvidenceType.SECTOR_PLACEMENT
        else:
            raise ValueError(f"Invalid evidence type: {s}")

    @staticmethod
    def to_string_list():
        return [v.name for v in EvidenceType]

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


# @title EvidenceResult
# @notice Shared evidence result type constants for PoRepMarket
class EvidenceResult(enum.Enum):
    NONE = 0
    PARTIAL = 10
    ACCEPTED = 20
    REJECTED = 30
    ACTIVE = 40
    INACTIVE = 50
    COVERED_BYTES_MISMATCH = 60

    @staticmethod
    def from_web3(s: str | int | None) -> "EvidenceResult":
        if s is None or s == "":
            raise ValueError(f"Invalid evidence result: {s}")

        s = str(s).strip().lower()

        if s in ("0", "none"):
            return EvidenceResult.NONE
        elif s in ("10", "partial"):
            return EvidenceResult.PARTIAL
        elif s in ("20", "accepted"):
            return EvidenceResult.ACCEPTED
        elif s in ("30", "rejected"):
            return EvidenceResult.REJECTED
        elif s in ("40", "active"):
            return EvidenceResult.ACTIVE
        elif s in ("50", "inactive"):
            return EvidenceResult.INACTIVE
        elif s in ("60", "covered_bytes_mismatch"):
            return EvidenceResult.COVERED_BYTES_MISMATCH
        else:
            raise ValueError(f"Invalid evidence result: {s}")

    @staticmethod
    def to_string_list():
        return [v.name for v in EvidenceResult]

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


# @notice EvidenceStatus struct represents the status of evidence for a deal
# @param activeCoveredBytes currently active bytes from adapter-checked evidence
# @param lastEvidenceRefreshEpoch epoch of the last evidence refresh
# @param reasonCode code representing the reason for the current status
# @param result current result code based on submitted evidence
# @param checkedItems claims or sectors checked in the reported refresh sweep
# @param totalItems claims or sectors that must be checked for the deal
@utils.json_dataclass()
class EvidenceStatus:
    active_covered_bytes: int
    last_evidence_refresh_epoch: int
    reason_code: int
    result: EvidenceResult
    checked_items: int
    total_items: int

    @staticmethod
    def from_web3(data) -> "EvidenceStatus":
        # noinspection PyArgumentList
        return EvidenceStatus(
            active_covered_bytes=data[0],
            last_evidence_refresh_epoch=data[1],
            reason_code=data[2],
            result=EvidenceResult.from_web3(data[3]),
            checked_items=data[4],
            total_items=data[5]
        )


class EvidenceAdapter(ContractService):
    # @notice Returns the identifier of the storage-checking mechanism implemented by this adapter
    # @dev PoRepMarket routes calls through the adapter address stored on the deal, not through this identifier
    # @return Adapter type identifier
    def get_evidence_type(self) -> EvidenceType:
        return EvidenceType.from_web3(self.call_contract(self.contract.functions.getEvidenceType()))

    # @notice Returns whether operators should assign this adapter to new deals
    # @dev An adapter may stop new deal setup while keeping reads and refreshes available for existing deals
    # @return True when the adapter is available for new deals
    def is_operational(self) -> bool:
        return self.call_contract(self.contract.functions.isOperational())

    # @notice Getter for the PoRepMarket contract address
    # @return Address of the PoRepMarket contract
    def get_porep_market_contract_address(self) -> EthAddress:
        return EthAddress(self.call_contract(self.contract.functions.getPoRepMarketAddress()))
