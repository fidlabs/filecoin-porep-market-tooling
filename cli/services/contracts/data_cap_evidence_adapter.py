from cli import utils
from cli.services.contracts.contract_service import ContractService
from cli.services.txsigner import TxSigner
from cli.services.web3_service import ActorId, EthAddress


@utils.json_dataclass()
class TransferParams:
    # pylint: disable=invalid-name
    FilAddress = tuple[bytes]
    BigInt = tuple[bytes, bool]

    to: FilAddress
    amount: BigInt
    operator_data: bytes

#FIXME: uncoment after merge PR https://github.com/fidlabs/porep-market/pull/87: ActivationContext
# @utils.json_dataclass()
# class ActivationContext:
#     deal_id: int
#     requested_size_bytes: int
#     client: EthAddress
#     duration_epochs: int
#     activation_tolerance_bps: int
#     provider: EthAddress

#FIXME: uncoment after merge PR https://github.com/fidlabs/porep-market/pull/87: ActivationDecision
# @utils.json_dataclass()
# class ActivationDecision:
#     covered_bytes: int
#     reason_code: int
#     result: int

class DataCapEvidenceAdapter(ContractService):
    _DATA_CAP_EVIDENCE_ADAPTER_ADDRESS: EthAddress | None = None

    def __init__(self, contract_address: EthAddress | None = None):
        if not contract_address and not DataCapEvidenceAdapter._DATA_CAP_EVIDENCE_ADAPTER_ADDRESS:
            from cli.services.contracts.porep_market import PoRepMarket
            DataCapEvidenceAdapter._DATA_CAP_EVIDENCE_ADAPTER_ADDRESS = PoRepMarket().get_data_cap_evidence_adapter_address()

        # noinspection PyTypeChecker
        super().__init__(contract_address or DataCapEvidenceAdapter._DATA_CAP_EVIDENCE_ADAPTER_ADDRESS,
                         self.abi_dir() / "DataCapEvidenceAdapter.json")

    # @notice This function transfers DataCap tokens from the client to the storage provider
    # @dev This function can only be called by the client
    # @param params The parameters for the transfer
    # @param dealId The id of the deal
    def submit_data_cap_batch(self, transfer_params: TransferParams, deal_id: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.submitDataCapBatch(
                (transfer_params.to, transfer_params.amount, transfer_params.operator_data), deal_id
            ), signer)

    # @notice Replaces all broken tracked allocations for a completed existing deal.
    # @dev Only callable by RESCUE_ROLE.
    # @param dealId The id of the deal to rescue.
    # @param params The DataCap transfer parameters that create replacement allocations.
    def rescue_deal_allocations(self, deal_id: int, transfer_params: TransferParams, signer: TxSigner) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.rescueDealAllocations(
                deal_id, (transfer_params.to, transfer_params.amount, transfer_params.operator_data)
            ), signer)

    # @notice getter to retrieve allocation ids for a deal with pagination
    # @param dealId the id of the deal
    # @param offset index to start from
    # @param limit max number of ids to return
    # @return ids allocation ids for the deal
    # @return sumOfAllocations total number of allocation ids for the deal
    def get_allocation_ids_per_deal(self, deal_id: int, offset: int, limit: int) -> tuple[list[ActorId], int]:
        return self.contract.functions.getAllocationIdsPerDeal(deal_id, offset, limit).call()

    # @notice custom getter to retrieve allocated size in deal
    # @param dealId The id of the deal
    # @return sizeOfAllocations size of allocations for the selected deal
    def get_size_of_allocations(self, deal_id: int) -> int:
        return self.contract.functions.getSizeOfAllocations(deal_id).call()

    # @notice getter to retrieve claim ids for a deal with pagination
    # @param dealId the id of the deal
    # @param offset pagination offset for the claim ids
    # @param limit pagination limit for the claim ids
    # @return ids list of claim ids for the given deal
    # @return total total number of claims for the given deal
    def get_claim_ids(self, deal_id: int, offset: int, limit: int) -> tuple[list[ActorId], int]:
        return self.contract.functions.getClaimIds(deal_id, offset, limit).call()

    # @notice Checks if the total active data size for the client with the specified provider matches the expected size
    # @dev This function can only be called by the validator of the deal
    # @param dealId The id of the deal
    # @return totalSizePerSp The total active data size for the client with the specified provider
    def is_data_size_matching(self, deal_id: int) -> bool:
        return self.contract.functions.isDataSizeMatching(deal_id).call()

    # @notice Returns whether the adapter can still process new evidence
    # @dev Returns false when the adapter is no longer operational, for example
    # when the DataCap adapter can no longer accept allocations or claims
    # @return True if the adapter can process new evidence, false if it is no longer operational
    def is_operational(self) -> bool:
        return self.contract.functions.isOperational().call()

    # @notice Getter for the evidence type
    # @return The evidence type as uint8
    def evidence_type(self) -> int:
        return self.contract.functions.evidenceType().call()

    # @notice custom getter to check if claim is terminated
    # @param claimId the id of the claim
    # @return isTerminated whether the claim is terminated
    # @return isTerminated whether the claim is terminated
    def terminated_claims(self, claim_id: int) -> bool:
        return self.contract.functions.terminatedClaims(claim_id).call()

    # @notice Getter for the PoRepMarket contract address
    # @return Address of the PoRepMarket contract
    def get_porep_market_contract_address(self) -> EthAddress:
        return self.contract.functions.getPoRepMarketAddress().call()

    #FIXME: uncoment after merge PR https://github.com/fidlabs/porep-market/pull/87: submit_evidence_batch
    # @notice Submits a batch of storage evidence.
    # @dev This function is only added for testing purpose, will be implemented in the future.
    # @return decision Dummy activation decision.
    # def submit_evidence_batch(self, context: ActivationContext, evidence_data: bytes) -> ActivationDecision:
    #     return self.contract.functions.submitEvidenceBatch(context, evidence_data).call()
