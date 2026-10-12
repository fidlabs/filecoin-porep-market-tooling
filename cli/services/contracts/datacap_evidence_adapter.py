import enum

from cli import utils
from cli.services.contract_service import TxInfo
from cli.services.contracts.evidence_adapter import EvidenceAdapter
from cli.services.txsigner import TxSigner
from cli.services.web3_service import EthAddress, FilAddress


@utils.json_dataclass()
class DataCapTransferParams:
    # pylint: disable=invalid-name
    FilAddress = tuple[bytes]
    BigInt = tuple[bytes, bool]

    to: FilAddress
    amount: BigInt
    operator_data: bytes


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
        return [v.name for v in DataCapAllocationStatus]

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


class DataCapEvidenceAdapter(EvidenceAdapter):
    def __init__(self, contract_address: EthAddress | FilAddress):
        super().__init__(contract_address, self.abi_dir() / "DataCapEvidenceAdapter.json")

    # @notice This function transfers DataCap tokens from the client to the storage provider
    # @dev This function can only be called by the client
    # @param params The parameters for the transfer
    # @param dealId The id of the deal
    def submit_datacap_batch(self, transfer_params: DataCapTransferParams, deal_id: int, signer: TxSigner) -> TxInfo:
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
    def rescue_deal_allocations(self, deal_id: int, transfer_params: DataCapTransferParams, signer: TxSigner) -> TxInfo:
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
        return self.call_contract(self.contract.functions.getAllocationIdsPerDeal(deal_id, offset, limit))

    # @notice custom getter to retrieve allocated bytes in deal
    # @param dealId The id of the deal
    # @return allocatedBytes allocated bytes for the selected deal
    def get_allocated_bytes(self, deal_id: int) -> int:
        return self.call_contract(self.contract.functions.getAllocatedBytes(deal_id))

    # @notice Closes DataCap posting for a deal in a separate transaction
    # @dev Only callable by the deal client while the deal is Accepted and posting is open
    # @param dealId The id of the deal
    def finish_datacap_posting(self, deal_id: int, signer: TxSigner) -> TxInfo:
        return self.sign_and_send_tx(self.contract.functions.finishDataCapPosting(deal_id), signer)

    # @notice Returns whether DataCap posting has been finished for a deal
    # @param dealId The id of the deal
    # @return True if posting is finished, false otherwise
    def is_datacap_posting_finished(self, deal_id: int) -> bool:
        return self.call_contract(self.contract.functions.isDataCapPostingFinished(deal_id))

    # @notice Getter for the DataCap allocation status of a deal
    # @param dealId The id of the deal
    # @return status The allocation status as uint8
    def get_deal_allocation_status(self, deal_id: int) -> DataCapAllocationStatus:
        return DataCapAllocationStatus.from_web3(self.call_contract(self.contract.functions.getDealAllocationStatus(deal_id)))

    # @notice getter to retrieve claim ids for a deal with pagination
    # @param dealId the id of the deal
    # @param offset pagination offset for the claim ids
    # @param limit pagination limit for the claim ids
    # @return ids list of claim ids for the given deal
    # @return sumOfClaims total number of claims for the given deal
    def get_claim_ids(self, deal_id: int, offset: int, limit: int) -> tuple[list[int], int]:
        return self.call_contract(self.contract.functions.getClaimIds(deal_id, offset, limit))

    # @notice custom getter to check if claim is terminated
    # @param claimId the id of the claim
    # @return isTerminated whether the claim is terminated
    def terminated_claims(self, claim_id: int) -> bool:
        return self.call_contract(self.contract.functions.terminatedClaims(claim_id))
