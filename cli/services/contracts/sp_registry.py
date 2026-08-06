from cli import utils
from cli.services.contract_service import ContractService
from cli.services.contracts.porep_market import (
    PoRepMarketDealRequest,
    PoRepMarketSLIThresholds,
)
from cli.services.txsigner import TxSigner
from cli.services.web3_service import ActorId, EthAddress


# @notice Payment token policy.
# @param allowed True when offers may use the token.
# @param minPricePer32GiBPerMonth Minimum monthly price per 32 GiB in token smallest units.
@utils.json_dataclass()
class SPRegistryTokenConfig:
    allowed: bool
    min_price_per_32_gib_per_month: int

    @staticmethod
    def from_web3(data) -> "SPRegistryTokenConfig":
        # noinspection PyArgumentList
        return SPRegistryTokenConfig(
            allowed=bool(data[0]),
            min_price_per_32_gib_per_month=int(data[1])
        )


# @notice Provider offer terms that define immutable offer shape
# @param minSizeBytes Minimum request size accepted by the offer
# @param maxSizeBytes Maximum request size accepted by the offer (0 = no maximum)
# @param minDurationEpochs Minimum paid service duration in epochs (0 = no minimum)
# @param maxDurationEpochs Maximum paid service duration in epochs (0 = no maximum)
@utils.json_dataclass()
class SPRegistryOfferTerms:
    min_size_bytes: int
    max_size_bytes: int
    min_duration_epochs: int
    max_duration_epochs: int

    @staticmethod
    def from_web3(data) -> "SPRegistryOfferTerms":
        if not data[1] or str(data[1]) == "0":
            raise RuntimeError("Offer terms not found")

        # noinspection PyArgumentList
        return SPRegistryOfferTerms(
            min_size_bytes=int(data[0]),
            max_size_bytes=int(data[1]),
            min_duration_epochs=int(data[2]),
            max_duration_epochs=int(data[3])
        )


# @notice Current payment configuration for one token on an offer.
# @param token ERC20 token address.
# @param active True when this token can be selected.
# @param pricePer32GiBPerMonth Monthly price per 32 GiB in token smallest units.
@utils.json_dataclass()
class SPRegistryOfferPaymentView:
    token: EthAddress
    active: bool
    price_per_32_gib_per_month: int

    def __post_init__(self):
        self.token = EthAddress(self.token)

    @staticmethod
    def from_web3(data) -> "SPRegistryOfferPaymentView":
        if not data[0] or not EthAddress(data[0]):
            raise RuntimeError("Offer payment view not found")

        # noinspection PyArgumentList
        return SPRegistryOfferPaymentView(
            token=EthAddress(data[0]),
            active=bool(data[1]),
            price_per_32_gib_per_month=int(data[2])
        )


# @notice Current offer data including all configured payment tokens.
# @param offerId Offer ID.
# @param provider Provider actor ID that owns the offer.
# @param active True when the offer participates in matching.
# @param terms Offer size and duration bounds.
# @param slis Promised offer SLIs.
# @param payments Current payment token rows configured on the offer.
@utils.json_dataclass()
class SPRegistryOfferView:
    offer_id: int
    provider_id: ActorId
    active: bool
    terms: SPRegistryOfferTerms
    slis: PoRepMarketSLIThresholds
    payments: list[SPRegistryOfferPaymentView]

    def __post_init__(self):
        self.provider_id = ActorId(self.provider_id)

    @staticmethod
    def from_web3(data, expected_offer_id: int | None = None) -> "SPRegistryOfferView":
        if not data[0] or str(data[0]) == "0":
            raise RuntimeError("Offer not found")

        if expected_offer_id is not None and expected_offer_id != data[0]:
            raise RuntimeError(f"Invalid offer returned from contract; expected offer_id {expected_offer_id}, got {data[0]}")

        # noinspection PyArgumentList
        return SPRegistryOfferView(
            offer_id=int(data[0]),
            provider_id=ActorId(data[1]),
            active=bool(data[2]),
            terms=SPRegistryOfferTerms.from_web3(data[3]),
            slis=PoRepMarketSLIThresholds.from_web3(data[4]),
            payments=[SPRegistryOfferPaymentView.from_web3(payment) for payment in data[5]]
        )


#  @notice Payment row for an offer and ERC20 token
#  @param token ERC20 token address
#  @param active True when this token row can be selected
#  @param pricePer32GiBPerMonth Monthly price per 32 GiB in token smallest units
@utils.json_dataclass()
class SPRegistryOfferPaymentInput(SPRegistryOfferPaymentView):
    pass


@utils.json_dataclass()
class SPRegistryOfferInput:
    provider_id: ActorId
    terms: SPRegistryOfferTerms
    slis: PoRepMarketSLIThresholds
    payments: list[SPRegistryOfferPaymentInput]

    def __post_init__(self):
        self.provider_id = ActorId(self.provider_id)


@utils.json_dataclass()
class SPRegistryProviderInput:
    provider_id: ActorId  # f0-id of the SP in Filecoin network
    organization_address: EthAddress
    available_bytes: int
    payee_address: EthAddress

    def __post_init__(self):
        self.provider_id = ActorId(self.provider_id)
        self.organization_address = EthAddress(self.organization_address)
        self.payee_address = EthAddress(self.payee_address)


# @notice Current provider registration and capacity data.
# @param provider Provider actor ID.
# @param organization Address that owns the provider registration.
# @param payee Address receiving provider payments.
# @param paused True when the provider is temporarily excluded from matching.
# @param blocked True when the provider is administratively blocked.
# @param availableBytes Total provider capacity available for deals.
# @param committedBytes Capacity already committed to activated deals.
# @param pendingBytes Capacity reserved by proposed deals.
@utils.json_dataclass()
class SPRegistryProviderView(SPRegistryProviderInput):
    paused: bool
    blocked: bool
    committed_bytes: int
    pending_bytes: int

    @staticmethod
    def from_web3(data, expected_provider_id: ActorId | None = None) -> "SPRegistryProviderView":
        if expected_provider_id is not None and expected_provider_id != ActorId(data[0]):
            raise RuntimeError(f"Invalid provider returned from contract; expected provider_id {expected_provider_id}, got {data[0]}")

        # noinspection PyArgumentList
        return SPRegistryProviderView(
            provider_id=ActorId(data[0]),
            organization_address=EthAddress(data[1]),
            payee_address=EthAddress(data[2]),
            paused=bool(data[3]),
            blocked=bool(data[4]),
            available_bytes=int(data[5]),
            committed_bytes=int(data[6]),
            pending_bytes=int(data[7]),
        )


# @notice Selected offer snapshot returned by SPRegistry
# @param provider Selected storage provider actor ID
# @param offerId Selected offer ID
# @param paymentToken ERC20 token selected for the deal
# @param payee Provider-level payment recipient frozen into the deal
# @param pricePer32GiBPerMonth Monthly price frozen into the deal
# @param promisedSLIs SLI terms promised by the selected offer
# @param reservedBytes Bytes reserved by the request
@utils.json_dataclass()
class SPRegistryProviderDealSelection:
    provider_id: ActorId
    offer_id: int
    payment_token_address: EthAddress
    payee_address: EthAddress
    price_per_32_gib_per_month: int
    promised_slis: PoRepMarketSLIThresholds
    reserved_bytes: int

    def __post_init__(self):
        self.provider_id = ActorId(self.provider_id)
        self.payment_token_address = EthAddress(self.payment_token_address)
        self.payee_address = EthAddress(self.payee_address)

    @staticmethod
    def from_web3(data) -> "SPRegistryProviderDealSelection":
        if not data[0] or str(data[0]) == "0":
            raise RuntimeError("Provider deal selection not found")

        # noinspection PyArgumentList
        return SPRegistryProviderDealSelection(
            provider_id=ActorId(data[0]),
            offer_id=int(data[1]),
            payment_token_address=EthAddress(data[2]),
            payee_address=EthAddress(data[3]),
            price_per_32_gib_per_month=int(data[4]),
            promised_slis=PoRepMarketSLIThresholds.from_web3(data[5]),
            reserved_bytes=int(data[6])
        )


class SPRegistry(ContractService):
    _SP_REGISTRY_ADDRESS: EthAddress | None = None

    def __init__(self, contract_address: EthAddress | None = None):
        if not contract_address and not SPRegistry._SP_REGISTRY_ADDRESS:
            from cli.services.contracts.porep_market import PoRepMarket
            SPRegistry._SP_REGISTRY_ADDRESS = PoRepMarket().get_sp_registry_contract_address()

        # noinspection PyTypeChecker
        super().__init__(contract_address or SPRegistry._SP_REGISTRY_ADDRESS,
                         self.abi_dir() / "SPRegistry.json")

    # @notice Registers a provider on behalf of an organization (admin/operator only).
    # @param provider Miner actor ID to register.
    # @param organization Organization address that controls the provider.
    # @param availableBytes Initial available capacity in bytes.
    # @param payee Payout recipient; defaults to organization when zero.
    def register_provider_for(self,
                              provider: SPRegistryProviderInput,
                              signer: TxSigner) -> str:
        #
        return self.sign_and_send_tx(
            self.contract.functions.registerProviderFor(
                provider.provider_id,
                provider.organization_address,
                provider.available_bytes,
                provider.payee_address
            ),
            signer
        )

    # @notice Check if a provider is registered
    # @param provider_id The provider actor ID
    # @return True if the provider is registered
    def is_provider_registered(self, provider_id: ActorId) -> bool:
        return self.call_contract(self.contract.functions.isProviderRegistered(provider_id))

    # @notice Returns all registered provider actor IDs.
    # @return Array of provider actor IDs.
    def get_providers(self) -> list[ActorId]:
        return [ActorId(provider_id) for provider_id in self.call_contract(self.contract.functions.getProviders())]

    def get_providers_views(self) -> list[SPRegistryProviderView]:
        return [self.get_provider_view(provider_id) for provider_id in self.get_providers()]

    # @notice Returns provider views owned by the given organization
    # @dev The contract has no by-organization getter; filters all providers client-side
    def get_providers_views_by_organization(self, organization_address: EthAddress) -> list[SPRegistryProviderView]:
        return [provider for provider in self.get_providers_views() if provider.organization_address == organization_address]

    # @notice Returns current provider registration and capacity data.
    # @param provider Provider actor ID.
    # @return view_ Current provider view.
    def get_provider_view(self, provider_id: ActorId) -> SPRegistryProviderView:
        return SPRegistryProviderView.from_web3(self.call_contract(self.contract.functions.getProviderView(provider_id)), provider_id)

    # @notice Check if address is authorized to act on behalf of a provider
    # @dev Admin and OPERATOR_ROLE always return true. Otherwise checks MinerUtils.isControllingAddress.
    # @param caller Address to check
    # @param provider Provider to check against
    # @return True if caller is authorized for provider
    def is_authorized_for_provider(self, caller: EthAddress, provider_id: ActorId) -> bool:
        return self.call_contract(self.contract.functions.isAuthorizedForProvider(caller, provider_id))

    # @notice Block a provider (admin only, excluded from matching)
    # @param provider The provider to block
    def block_provider(self, provider_id: ActorId, signer: TxSigner) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.blockProvider(provider_id),
            signer
        )

    # @notice Unblock a provider (admin only)
    # @param provider The provider to unblock
    def unblock_provider(self, provider_id: ActorId, signer: TxSigner) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.unblockProvider(provider_id),
            signer
        )

    # @notice Pause a provider (excluded from matching)
    # @param provider The provider to pause
    def pause_provider(self, provider_id: ActorId, signer: TxSigner) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.pauseProvider(provider_id),
            signer
        )

    # @notice Unpause a provider (available for matching)
    # @param provider The provider to unpause
    def unpause_provider(self, provider_id: ActorId, signer: TxSigner) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.unpauseProvider(provider_id),
            signer
        )

    # @notice Updates provider available capacity.
    # @param provider Provider actor ID.
    # @param availableBytes New available capacity in bytes.
    def update_available_space(self, provider_id: ActorId, available_bytes: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.updateAvailableSpace(provider_id, available_bytes),
            signer
        )

    # @notice Updates provider payment recipient.
    # @param provider Provider actor ID.
    # @param payee New payment recipient.
    def set_payee(self, provider_id: ActorId, payee_address: EthAddress, signer: TxSigner) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.setPayee(provider_id, payee_address),
            signer
        )

    # @notice Sets whether a payment token can be used by offers.
    # @param token ERC20 token address.
    # @param allowed True to allow the token, false to remove it from matching.
    # @param minPricePer32GiBPerMonth Minimum monthly price per 32 GiB in token smallest units.
    def set_payment_token(self, token: EthAddress, token_config: SPRegistryTokenConfig, signer: TxSigner) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.setPaymentToken(token, token_config.allowed, token_config.min_price_per_32_gib_per_month),
            signer
        )

    # @notice Returns allowed payment token addresses.
    # @return tokens Array of allowed token addresses.
    def get_payment_tokens(self) -> list[EthAddress]:
        return [EthAddress(token) for token in self.call_contract(self.contract.functions.getPaymentTokens())]

    # @notice Returns payment token policy.
    # @param token ERC20 token address.
    # @return config Token policy.
    def get_payment_token_config(self, token: EthAddress) -> SPRegistryTokenConfig:
        return SPRegistryTokenConfig.from_web3(self.call_contract(self.contract.functions.getPaymentTokenConfig(token)))

    # @notice Creates an active provider offer.
    # @param provider Provider actor ID.
    # @param terms Immutable offer size and duration bounds.
    # @param slis Immutable promised SLIs.
    # @param payments Initial payment rows.
    # @return offerId Created offer ID.
    def create_offer(self, offer: SPRegistryOfferInput, signer: TxSigner) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.createOffer(
                offer.provider_id,
                (offer.terms.min_size_bytes, offer.terms.max_size_bytes, offer.terms.min_duration_epochs, offer.terms.max_duration_epochs),
                (offer.slis.retrievability_bps, offer.slis.bandwidth_bytes_per_second, offer.slis.latency_ms, offer.slis.indexing_pct),
                [(payment.token, payment.active, payment.price_per_32_gib_per_month) for payment in offer.payments]
            ),
            signer
        )

    # @notice Enables or disables an offer for matching.
    # @param offerId Offer ID.
    # @param active True to enable the offer, false to disable it.
    def set_offer_active(self, offer_id: int, active: bool, signer: TxSigner) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.setOfferActive(offer_id, active),
            signer
        )

    # @notice Updates or adds a mutable offer payment row.
    # @param offerId Offer ID.
    # @param token ERC20 token address.
    # @param active True when the token row can be selected.
    # @param pricePer32GiBPerMonth Monthly price per 32 GiB in token smallest units.
    def set_offer_payment(self, offer_id: int, payment: SPRegistryOfferPaymentInput, signer: TxSigner) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.setOfferPayment(offer_id, payment.token, payment.active, payment.price_per_32_gib_per_month),
            signer
        )

    # @notice Returns offer data plus the payment row for one token.
    # @param offerId Offer ID.
    # @return view_ Current offer view for the requested payment token.
    def get_offer_view(self, offer_id: int) -> SPRegistryOfferView:
        return SPRegistryOfferView.from_web3(self.call_contract(self.contract.functions.getOfferView(offer_id)), offer_id)

    # @notice Returns all offer IDs created by a provider.
    # @param provider Provider actor ID.
    # @return offerIds Offer IDs for the provider.
    def get_offers_by_provider(self, provider_id: ActorId) -> list[int]:
        return [int(offer_id) for offer_id in self.call_contract(self.contract.functions.getOffersByProvider(provider_id))]

    # @notice Previews automatic offer matching without reserving capacity.
    # @param request Client deal request.
    # @return selection Selected offer snapshot, or zero provider when no offer matches.
    def preview_provider_for_deal(self, request: PoRepMarketDealRequest) -> SPRegistryProviderDealSelection:
        slis = request.required_slis

        return SPRegistryProviderDealSelection.from_web3(
            self.call_contract(
                self.contract.functions.previewProviderForDeal(
                    (
                        request.manifest_hash,
                        request.requested_size_bytes,
                        request.max_price_per_32_gib_per_month,
                        request.manifest_location,
                        request.payment_token_address,
                        request.duration_days,
                        request.deal_type,
                        (slis.retrievability_bps, slis.bandwidth_bytes_per_second, slis.latency_ms, slis.indexing_pct)
                    )
                )
            ))

    # @notice Selects an offer automatically and reserves pending provider capacity.
    # @param request Client deal request.
    # @return selection Selected offer snapshot.
    def reserve_provider_for_deal(self, request: PoRepMarketDealRequest, signer: TxSigner) -> str:
        slis = request.required_slis

        return self.sign_and_send_tx(
            self.contract.functions.reserveProviderForDeal(
                (
                    request.manifest_hash,
                    request.requested_size_bytes,
                    request.max_price_per_32_gib_per_month,
                    request.manifest_location,
                    request.payment_token_address,
                    request.duration_days,
                    request.deal_type,
                    (slis.retrievability_bps, slis.bandwidth_bytes_per_second, slis.latency_ms, slis.indexing_pct)
                )
            ),
            signer
        )

    # @notice Previews a specific offer for a deal without reserving capacity.
    # @param offerId Offer ID to validate.
    # @param request Client deal request.
    # @return selection Selected offer snapshot, or zero provider when the offer does not match.
    # @return reason OfferMatch reason code; OfferMatch.OK when the offer is eligible.
    def preview_offer_for_deal(self, offer_id: int, request: PoRepMarketDealRequest) -> tuple[SPRegistryProviderDealSelection, int]:
        slis = request.required_slis

        selection, reason = self.call_contract(
            self.contract.functions.previewOfferForDeal(
                offer_id,
                (
                    request.manifest_hash,
                    request.requested_size_bytes,
                    request.max_price_per_32_gib_per_month,
                    request.manifest_location,
                    request.payment_token_address,
                    request.duration_days,
                    request.deal_type,
                    (slis.retrievability_bps, slis.bandwidth_bytes_per_second, slis.latency_ms, slis.indexing_pct)
                )
            )
        )

        return SPRegistryProviderDealSelection.from_web3(selection), int(reason)

    # @notice Validates a specific offer and reserves pending provider capacity.
    # @param offerId Offer ID to validate.
    # @param request Client deal request.
    # @return selection Selected offer snapshot.
    def reserve_offer_for_deal(self, offer_id: int, request: PoRepMarketDealRequest, signer: TxSigner) -> str:
        slis = request.required_slis

        return self.sign_and_send_tx(
            self.contract.functions.reserveOfferForDeal(
                offer_id,
                (
                    request.manifest_hash,
                    request.requested_size_bytes,
                    request.max_price_per_32_gib_per_month,
                    request.manifest_location,
                    request.payment_token_address,
                    request.duration_days,
                    request.deal_type,
                    (slis.retrievability_bps, slis.bandwidth_bytes_per_second, slis.latency_ms, slis.indexing_pct)
                )
            ),
            signer
        )

    # @notice Checks whether a provider is already assigned to a manifest.
    # @param manifestHash Manifest hash used as data identity.
    # @param provider Provider actor ID.
    # @return True when provider is locked for the manifest.
    def is_manifest_assigned_to_provider(self, manifest_hash: bytes, provider_id: ActorId) -> bool:
        return self.call_contract(self.contract.functions.isManifestAssignedToProvider(manifest_hash, provider_id))

    # @notice Releases committed provider capacity and clears the manifest/provider assignment.
    # @param provider Provider actor ID.
    # @param sizeBytes Capacity to release.
    # @param manifestHash Manifest hash whose provider assignment should be cleared.
    def release_capacity(self, provider_id: ActorId, size_bytes: int, manifest_hash: bytes, signer: TxSigner) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.releaseCapacity(provider_id, size_bytes, manifest_hash),
            signer
        )

    # @notice Releases pending provider capacity and clears the manifest/provider assignment.
    # @param provider Provider actor ID.
    # @param sizeBytes Pending capacity to release.
    # @param manifestHash Manifest hash whose provider assignment should be cleared.
    def release_pending_capacity(self, provider_id: ActorId, size_bytes: int, manifest_hash: bytes, signer: TxSigner) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.releasePendingCapacity(provider_id, size_bytes, manifest_hash),
            signer
        )

    # @notice Converts pending capacity into committed capacity.
    # @param provider Provider actor ID.
    # @param estimatedSizeBytes Pending bytes reserved by the deal request.
    # @param actualSizeBytes Actual activated bytes.
    def commit_capacity(self, provider_id: ActorId, estimated_size_bytes: int, actual_size_bytes: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.commitCapacity(provider_id, estimated_size_bytes, actual_size_bytes),
            signer
        )
