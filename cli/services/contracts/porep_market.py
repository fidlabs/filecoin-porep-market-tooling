from cli import utils
from cli.services.contracts.contract_service import ContractService
from cli.services.contracts.types.deal import PoRepMarketDealRequest, PoRepMarketDeal, PoRepMarketDealCapacity, PoRepMarketDealData, PoRepMarketDealPayment, PoRepMarketDealService, PoRepMarketDealState, PoRepMarketDealTermsView, PoRepMarketDealTiming, PoRepMarketDealView
from cli.services.contracts.types.evidence import EvidenceStatus
from cli.services.contracts.types.sli import SLIThresholds
from cli.services.txsigner import TxSigner
from cli.services.web3_service import EthAddress, ActorId


class PoRepMarket(ContractService):
    def __init__(self, contract_address: EthAddress | None = None):
        super().__init__(contract_address or utils.get_env_required("POREP_MARKET", required_type=EthAddress),
                         self.abi_dir() / "PoRepMarket.json")

    # @notice Proposes a deal
    # @param request The client's request for a storage deal (SharedTypes.DealRequest)
    def propose_deal(self, request: PoRepMarketDealRequest, signer: TxSigner) -> str:
        slis = request.required_slis

        return self.sign_and_send_tx(
            self.contract.functions.proposeDeal((
                request.manifest_hash,
                request.requested_size_bytes,
                request.max_price_per_32_gib_per_month,
                request.manifest_location,
                request.payment_token,
                request.duration_days,
                (slis.retrievability_bps, slis.bandwidth_bytes_per_second, slis.latency_ms, slis.indexing_pct)
            )), signer)

    # @notice Gets the complete generic read model for one deal in a single eth_call
    # @param dealId The id of the deal
    # @return dealView Complete generic deal snapshot
    def get_deal_view(self, deal_id: int) -> PoRepMarketDealView:
        return PoRepMarketDealView.from_web3(self.contract.functions.getDealView(deal_id).call(), expected_deal_id=deal_id)

    # @notice Gets a page of complete deal snapshots
    # @param offset Zero-based index in the global deal ID list
    # @param limit Maximum number of deal views to return
    # @return dealViews Page of complete deal snapshots
    def get_deal_views(self, offset: int, limit: int) -> list[PoRepMarketDealView]:
        return [PoRepMarketDealView.from_web3(view) for view in
                self.contract.functions.getDealViews(offset, limit).call()]

    # @notice Gets the total number of deals
    def get_deal_count(self) -> int:
        return self.contract.functions.getDealCount().call()

    # @notice Gets a page of deal IDs
    # @param offset Zero-based index in the global deal ID list
    # @param limit Maximum number of deal IDs to return
    # @return (dealIds, total) Page of deal IDs and total number of deals at call time
    def get_deal_ids(self, offset: int, limit: int) -> tuple[list[int], int]:
        deal_ids, total = self.contract.functions.getDealIds(offset, limit).call()
        return list(deal_ids), int(total)

    # @notice Gets a page of deal IDs for one lifecycle state
    # @param state Deal lifecycle state code
    # @param offset Zero-based index in the state's deal ID list
    # @param limit Maximum number of deal IDs to return
    # @return (dealIds, total) Page of deal IDs and total number of deals in this state at call time
    def get_deal_ids_by_state(self, state: PoRepMarketDealState, offset: int, limit: int) -> tuple[list[int], int]:
        deal_ids, total = self.contract.functions.getDealIdsByState(state.value, offset, limit).call()
        return list(deal_ids), int(total)

    # @notice Gets a deal
    # @param dealId The id of the deal
    # @return deal The deal
    def get_deal(self, deal_id: int) -> PoRepMarketDeal:
        return PoRepMarketDeal.from_web3(self.contract.functions.getDeal(deal_id).call(), expected_deal_id=deal_id)

    # @notice Gets the data fields for a deal
    # @param dealId The id of the deal
    # @return dealData The deal data
    #
    def get_deal_data(self, deal_id: int) -> PoRepMarketDealData:
        return PoRepMarketDealData.from_web3(self.contract.functions.getDealData(deal_id).call(), expected_deal_id=deal_id)

    # @notice Gets the terms for a deal
    # @param dealId The id of the deal
    # @return terms The deal terms
    def get_deal_terms(self, deal_id: int) -> PoRepMarketDealTermsView:
        return PoRepMarketDealTermsView.from_web3(self.contract.functions.getDealTerms(deal_id).call(), expected_deal_id=deal_id)

    # @notice Gets the timing for a deal
    # @param dealId The id of the deal
    # @return timing The deal timing
    def get_deal_timing(self, deal_id: int) -> PoRepMarketDealTiming:
        return PoRepMarketDealTiming.from_web3(self.contract.functions.getDealTiming(deal_id).call(), expected_deal_id=deal_id)

    # @notice Gets the service window for a deal
    # @param dealId The id of the deal
    # @return service The deal service window
    def get_deal_service(self, deal_id: int) -> PoRepMarketDealService:
        return PoRepMarketDealService.from_web3(self.contract.functions.getDealService(deal_id).call(), expected_deal_id=deal_id)

    # @notice Gets the capacity for a deal
    # @param dealId The id of the deal
    # @return capacity The deal capacity
    def get_deal_capacity(self, deal_id: int) -> PoRepMarketDealCapacity:
        return PoRepMarketDealCapacity.from_web3(self.contract.functions.getDealCapacity(deal_id).call(), expected_deal_id=deal_id)

    # @notice Gets the payments for a deal
    # @param dealId The id of the deal
    # @return payments The deal payments    
    def get_deal_payments(self, deal_id: int) -> PoRepMarketDealPayment:
        return PoRepMarketDealPayment.from_web3(self.contract.functions.getDealPayment(deal_id).call(), expected_deal_id=deal_id)

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

    # @notice Gets all deals
    # @return deals Array of all deal proposals
    def get_deals(self) -> list[PoRepMarketDeal]:
        return [PoRepMarketDeal.from_web3(deal) for deal in self.contract.functions.getDeals().call()]

    # @notice Rejects a deal in Accepted state before rail is set
    # @dev Only callable by the admin
    # @param dealId The id of the deal proposal
    def reject_accepted_deal(self, deal_id: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.rejectAcceptedDeal(deal_id), signer)

    # @notice Updates the deal activation padding
    # @param padding The new padding value
    def set_deal_activation_padding(self, padding: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.setDealActivationPadding(padding), signer)

    # @notice Getter for deal activation padding
    # @return padding Current padding value
    def get_deal_activation_padding(self) -> int:
        return self.contract.functions.getDealActivationPadding().call()

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


    def refresh_evidence_status(self, deal_id: int, evidence_data: bytes, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.refreshEvidenceStatus(deal_id, evidence_data), signer)

    # @notice Reads current evidence status for a deal through its assigned adapter
    # @param dealId The id of the deal
    # @return status Current evidence status
    def current_evidence_status(self, deal_id: int) -> EvidenceStatus:
        status = self.contract.functions.currentEvidenceStatus(deal_id).call()
        return EvidenceStatus(
            active_covered_bytes=int(status[0]),
            last_evidence_refresh_epoch=int(status[1]),
            reason_code=int(status[2]),
            result=int(status[3])
        )

    # @notice Gets the SLI thresholds required by the client for a deal
    # @param dealId The id of the deal
    # @return slis The required SLI thresholds
    def get_deal_slis(self, deal_id: int) -> SLIThresholds:
        slis = self.contract.functions.getDealSLIs(deal_id).call()
        return SLIThresholds(
            retrievability_bps=int(slis[0]),
            bandwidth_bytes_per_second=int(slis[1]),
            latency_ms=int(slis[2]),
            indexing_pct=int(slis[3])
        )

    # @notice Gets the manifest location for a deal
    # @param dealId The id of the deal
    def get_manifest_location(self, deal_id: int) -> str:
        return self.contract.functions.getManifestLocation(deal_id).call()

    # @notice Updates the manifest location for a deal
    # @param dealId The id of the deal
    # @param newManifestLocation The new manifest location
    def update_manifest_location(self, deal_id: int, new_manifest_location: str, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.updateManifestLocation(deal_id, new_manifest_location), signer)

    # @notice Rejects a deal whose proposal has expired
    # @param dealId The id of the deal proposal
    def reject_expired_deal(self, deal_id: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.rejectExpiredDeal(deal_id), signer)

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

