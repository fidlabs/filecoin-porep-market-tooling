import re

from cli import utils
from cli.services.contract_service import ContractService
from cli.services.contracts.datacap_evidence_adapter import DataCapEvidenceStatus
from cli.services.contracts.porep_market import (
    PoRepMarketDeal,
    PoRepMarketSLIThresholds,
    PoRepMarketDealState,
)
from cli.services.web3_service import EthAddress, FilAddress


# @notice DealData struct represents the data associated with a deal
# @param manifestHash commitment for piece set
# @param manifestLocation URL or path for humans/tools; contracts do not fetch or trust it.
@utils.json_dataclass()
class PoRepMarketDealData:
    manifest_hash: bytes
    manifest_location: str

    @staticmethod
    def from_web3(data) -> "PoRepMarketDealData":
        if not data[0] or data[0] == b"":
            raise RuntimeError("Deal data not found")

        # noinspection PyArgumentList
        return PoRepMarketDealData(
            manifest_hash=data[0],
            manifest_location=re.sub(r"\s+", "", data[1])
        )


# @notice Frozen size and duration terms for a deal.
@utils.json_dataclass()
class PoRepMarketDealTermsView:
    requested_size_bytes: int
    duration_epochs: int

    @staticmethod
    def from_web3(data) -> "PoRepMarketDealTermsView":
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
        if not data[0] or str(data[0]) == "0":
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
        # noinspection PyArgumentList
        return PoRepMarketDealCapacity(
            reserved_bytes=int(data[0]),
            committed_bytes=int(data[1])
        )


# @notice Payment fields exposed through DealView.
@utils.json_dataclass()
class PoRepMarketDealPayment:
    payment_token: EthAddress
    payee: EthAddress
    price_per_32_gib_per_month: int
    billed_32_gib_units: int
    rail_max_rate_per_epoch: int

    def __post_init__(self):
        self.payment_token = EthAddress(self.payment_token)
        self.payee = EthAddress(self.payee)

    @staticmethod
    def from_web3(data) -> "PoRepMarketDealPayment":
        if not data[0] or not EthAddress(data[0]):
            raise RuntimeError("Deal payment not found")

        # noinspection PyArgumentList
        return PoRepMarketDealPayment(
            payment_token=EthAddress(data[0]),
            payee=EthAddress(data[1]),
            price_per_32_gib_per_month=int(data[2]),
            billed_32_gib_units=int(data[3]),
            rail_max_rate_per_epoch=int(data[4])
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
    service: PoRepMarketDealService
    capacity: PoRepMarketDealCapacity
    payment: PoRepMarketDealPayment
    provider_organization_address: EthAddress
    evidence_status: DataCapEvidenceStatus

    def __post_init__(self):
        self.provider_organization_address = EthAddress(self.provider_organization_address)

    @staticmethod
    def from_web3(data, expected_deal_id: int | None = None) -> "PoRepMarketDealView":
        # noinspection PyArgumentList
        return PoRepMarketDealView(
            deal=PoRepMarketDeal.from_web3(data[0], expected_deal_id),
            data=PoRepMarketDealData.from_web3(data[1]),
            required_slis=PoRepMarketSLIThresholds.from_web3(data[2]),
            terms=PoRepMarketDealTermsView.from_web3(data[3]),
            service=PoRepMarketDealService.from_web3(data[4]),
            capacity=PoRepMarketDealCapacity.from_web3(data[5]),
            payment=PoRepMarketDealPayment.from_web3(data[6]),
            provider_organization_address=EthAddress(data[7]),
            evidence_status=DataCapEvidenceStatus.from_web3(data[8])
        )


class PoRepMarketViewHelper(ContractService):
    def __init__(self, contract_address: EthAddress | FilAddress | None = None):
        super().__init__(contract_address or utils.get_env_required("POREP_MARKET_VIEW_HELPER", required_type=EthAddress.from_any),
                         self.abi_dir() / "PoRepMarketViewHelper.json")

    # @notice PoRepMarket contract used to fetch deal data.
    def porep_market_contract(self) -> EthAddress:
        return EthAddress(self.call_contract(self.contract.functions.POREPMARKET_CONTRACT()))

    # @notice Gets the complete generic read model for one deal.
    # @param dealId The id of the deal.
    # @return dealView Complete generic deal snapshot.
    def get_deal_view(self, deal_id: int) -> PoRepMarketDealView:
        return PoRepMarketDealView.from_web3(self.call_contract(self.contract.functions.getDealView(deal_id)), deal_id)

    # @notice Gets a caller-sized page of complete generic deal views.
    # @param offset Zero-based index in the creation-order deal list.
    # @param limit Maximum number of deal views to return.
    # @return dealViews Page of complete generic deal snapshots.
    # @return total Total number of created deals at call time.
    def get_deal_views(self, offset: int | None = None, limit: int | None = None) -> list[PoRepMarketDealView]:
        return [PoRepMarketDealView.from_web3(view) for view in
                self.call_contract_paginated(self.contract.functions.getDealViews, offset, limit)]

    # @notice Gets a caller-sized page of complete deal views for an organization and state.
    # @param organization The address of the organization.
    # @param state The state of the deals to retrieve.
    # @param offset Zero-based index in the organization's state-specific deal list.
    # @param limit Maximum number of deal views to return.
    # @return dealViews Page of complete generic deal snapshots.
    # @return total Total number of matching deals at call time.
    def get_deal_views_for_organization_by_state(self,
                                                 organization_address: EthAddress,
                                                 state: PoRepMarketDealState,
                                                 offset: int | None = None,
                                                 limit: int | None = None) -> list[PoRepMarketDealView]:
        #
        return [PoRepMarketDealView.from_web3(view) for view in
                self.call_contract_paginated(self.contract.functions.getDealViewsForOrganizationByState,
                                             offset,
                                             limit,
                                             organization_address,
                                             state.value)]
