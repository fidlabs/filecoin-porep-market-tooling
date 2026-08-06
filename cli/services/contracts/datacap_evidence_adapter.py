import enum

from cli import utils
from cli.services.contract_service import ContractService
from cli.services.txsigner import TxSigner
from cli.services.web3_service import EthAddress


@utils.json_dataclass()
class DataCapTransferParams:
    # pylint: disable=invalid-name
    FilAddress = tuple[bytes]
    BigInt = tuple[bytes, bool]

    to: FilAddress
    amount: BigInt
    operator_data: bytes


# @title EvidenceTypes
# @notice Shared evidence type constants for PoRepMarket
class DataCapEvidenceType(enum.Enum):
    NONE = 0
    VERIF_REG_CLAIMS = 10

    @staticmethod
    def from_web3(s: str | int | None) -> "DataCapEvidenceType":
        if s is None or s == "":
            raise ValueError(f"Invalid evidence type: {s}")

        s = str(s).strip().lower()

        if s in ("0", "none"):
            return DataCapEvidenceType.NONE
        elif s in ("10", "verif_reg_claims"):
            return DataCapEvidenceType.VERIF_REG_CLAIMS
        else:
            raise ValueError(f"Invalid evidence type: {s}")

    @staticmethod
    def to_string_list():
        return [_type.name for _type in DataCapEvidenceType]

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


# @title DataCapAllocationStatus
# @notice Lifecycle status of a DataCap allocation per deal tracked by the adapter
class DataCapAllocationStatus(enum.Enum):
    NONE = 0
    ALLOCATED = 10
    CLAIMED = 20
    INACTIVE = 30

    @staticmethod
    def from_web3(s: str | int | None) -> "DataCapAllocationStatus":
        if s is None or s == "":
            raise ValueError(f"Invalid DataCap allocation status: {s}")

        s = str(s).strip().lower()

        if s in ("0", "none"):
            return DataCapAllocationStatus.NONE
        elif s in ("10", "allocated"):
            return DataCapAllocationStatus.ALLOCATED
        elif s in ("20", "claimed"):
            return DataCapAllocationStatus.CLAIMED
        elif s in ("30", "inactive"):
            return DataCapAllocationStatus.INACTIVE
        else:
            raise ValueError(f"Invalid DataCap allocation status: {s}")

    @staticmethod
    def to_string_list():
        return [_status.name for _status in DataCapAllocationStatus]

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


# @title EvidenceResult
# @notice Shared evidence result type constants for PoRepMarket
class DataCapEvidenceResult(enum.Enum):
    NONE = 0
    PARTIAL = 10
    ACCEPTED = 20
    REJECTED = 30
    ACTIVE = 40
    INACTIVE = 50
    COVERED_BYTES_MISMATCH = 60

    @staticmethod
    def from_web3(s: str | int | None) -> "DataCapEvidenceResult":
        if s is None or s == "":
            raise ValueError(f"Invalid DataCap evidence result: {s}")

        s = str(s).strip().lower()

        if s in ("0", "none"):
            return DataCapEvidenceResult.NONE
        elif s in ("10", "partial"):
            return DataCapEvidenceResult.PARTIAL
        elif s in ("20", "accepted"):
            return DataCapEvidenceResult.ACCEPTED
        elif s in ("30", "rejected"):
            return DataCapEvidenceResult.REJECTED
        elif s in ("40", "active"):
            return DataCapEvidenceResult.ACTIVE
        elif s in ("50", "inactive"):
            return DataCapEvidenceResult.INACTIVE
        elif s in ("60", "covered_bytes_mismatch"):
            return DataCapEvidenceResult.COVERED_BYTES_MISMATCH
        else:
            raise ValueError(f"Invalid DataCap evidence result: {s}")

    @staticmethod
    def to_string_list():
        return [_result.name for _result in DataCapEvidenceResult]

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


# @notice EvidenceStatus struct represents the status of evidence for a deal
# @param activeCoveredBytes currently active bytes from adapter-checked evidence
# @param lastEvidenceRefreshEpoch epoch of the last evidence refresh
# @param reasonCode code representing the reason for the current status
# @param result current result code based on submitted evidence
# @param checkedClaims number of claims already checked in the current refresh sweep
# @param totalClaims total number of claims that must be checked for the deal
@utils.json_dataclass()
class DataCapEvidenceStatus:
    active_covered_bytes: int
    last_evidence_refresh_epoch: int
    reason_code: int
    result: DataCapEvidenceResult
    checked_claims: int
    total_claims: int

    @staticmethod
    def from_web3(data) -> "DataCapEvidenceStatus":
        if data[0] is None:
            raise ValueError("DataCap evidence status not found")

        # noinspection PyArgumentList
        return DataCapEvidenceStatus(
            active_covered_bytes=data[0],
            last_evidence_refresh_epoch=data[1],
            reason_code=data[2],
            result=DataCapEvidenceResult.from_web3(data[3]),
            checked_claims=data[4],
            total_claims=data[5]
        )


class DataCapEvidenceAdapter(ContractService):
    _DATACAP_EVIDENCE_ADAPTER_ADDRESS: EthAddress | None = None

    def __init__(self, contract_address: EthAddress | None = None):
        if not contract_address and not DataCapEvidenceAdapter._DATACAP_EVIDENCE_ADAPTER_ADDRESS:
            from cli.services.contracts.porep_market import PoRepMarket
            DataCapEvidenceAdapter._DATACAP_EVIDENCE_ADAPTER_ADDRESS = PoRepMarket().get_global_evidence_adapter_address()

        # noinspection PyTypeChecker
        super().__init__(contract_address or DataCapEvidenceAdapter._DATACAP_EVIDENCE_ADAPTER_ADDRESS,
                         self.abi_dir() / "DataCapEvidenceAdapter.json")

    # @notice This function transfers DataCap tokens from the client to the storage provider
    # @dev This function can only be called by the client
    # @param params The parameters for the transfer
    # @param dealId The id of the deal
    def submit_datacap_batch(self, transfer_params: DataCapTransferParams, deal_id: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.submitDataCapBatch(
                (transfer_params.to, transfer_params.amount, transfer_params.operator_data),
                deal_id
            ),
            signer
        )

    # @notice Replaces all broken tracked allocations for a completed existing deal.
    # @dev Only callable by RESCUE_ROLE.
    # @param dealId The id of the deal to rescue.
    # @param params The DataCap transfer parameters that create replacement allocations.
    def rescue_deal_allocations(self, deal_id: int, transfer_params: DataCapTransferParams, signer: TxSigner) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.rescueDealAllocations(
                deal_id,
                (transfer_params.to, transfer_params.amount, transfer_params.operator_data)
            ),
            signer
        )

    # @notice getter to retrieve allocation ids for a deal with pagination
    # @param dealId the id of the deal
    # @param offset index to start from
    # @param limit max number of ids to return
    # @return ids allocation ids for the deal
    # @return sumOfAllocations total number of allocation ids for the deal
    def get_allocation_ids_per_deal(self, deal_id: int, offset: int, limit: int) -> tuple[list[int], int]:
        return self.contract.functions.getAllocationIdsPerDeal(deal_id, offset, limit).call()

    # @notice custom getter to retrieve allocated bytes in deal
    # @param dealId The id of the deal
    # @return allocatedBytes allocated bytes for the selected deal
    def get_allocated_bytes(self, deal_id: int) -> int:
        return self.contract.functions.getAllocatedBytes(deal_id).call()

    # @notice Closes DataCap posting for a deal in a separate transaction
    # @dev Only callable by the deal client while the deal is Accepted and posting is open
    # @param dealId The id of the deal
    def finish_datacap_posting(self, deal_id: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.finishDataCapPosting(deal_id), signer)

    # @notice Returns whether DataCap posting has been finished for a deal
    # @param dealId The id of the deal
    # @return True if posting is finished, false otherwise
    def is_datacap_posting_finished(self, deal_id: int) -> bool:
        return self.contract.functions.isDataCapPostingFinished(deal_id).call()

    # @notice Getter for the DataCap allocation status of a deal
    # @param dealId The id of the deal
    # @return status The allocation status as uint8
    def get_deal_allocation_status(self, deal_id: int) -> DataCapAllocationStatus:
        return DataCapAllocationStatus.from_web3(self.contract.functions.getDealAllocationStatus(deal_id).call())

    # @notice getter to retrieve claim ids for a deal with pagination
    # @param dealId the id of the deal
    # @param offset pagination offset for the claim ids
    # @param limit pagination limit for the claim ids
    # @return ids list of claim ids for the given deal
    # @return sumOfClaims total number of claims for the given deal
    def get_claim_ids(self, deal_id: int, offset: int, limit: int) -> tuple[list[int], int]:
        return self.contract.functions.getClaimIds(deal_id, offset, limit).call()

    # @notice Returns whether the adapter can still process new evidence
    # @dev Returns false when the adapter is no longer operational, for example
    # when the DataCap adapter can no longer accept allocations or claims
    # @return True if the adapter can process new evidence, false if it is no longer operational
    def is_operational(self) -> bool:
        return self.contract.functions.isOperational().call()

    # @notice Getter for the evidence type
    # @return The evidence type as uint8
    def evidence_type(self) -> DataCapEvidenceType:
        return DataCapEvidenceType.from_web3(self.contract.functions.evidenceType().call())

    # @notice custom getter to check if claim is terminated
    # @param claimId the id of the claim
    # @return isTerminated whether the claim is terminated
    def terminated_claims(self, claim_id: int) -> bool:
        return self.contract.functions.terminatedClaims(claim_id).call()

    # @notice Getter for the PoRepMarket contract address
    # @return Address of the PoRepMarket contract
    def get_porep_market_contract_address(self) -> EthAddress:
        return self.contract.functions.getPoRepMarketAddress().call()
