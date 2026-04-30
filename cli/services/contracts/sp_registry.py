import os

from eth_account.types import PrivateKeyType

from cli import utils
from cli.services.contracts.contract_service import ContractService
from cli.services.web3_service import Address, ActorId


@utils.json_dataclass()
class SPRegistrySLIThresholds:
    retrievability_bps: int  # Valid range: 0-10000 (basis points, e.g. 7550 = 75.50%). 0 means "don't care"
    bandwidth_mbps: int  # Capped at ~64 Gbps
    latency_ms: int
    indexing_pct: int  # Valid range: 0-100. 0 means "don't care"


@utils.json_dataclass()
class SPRegistryProvider:
    provider_id: ActorId  # f0-id of the SP in Filecoin network
    organization_address: Address
    capabilities: SPRegistrySLIThresholds
    available_bytes: int
    price_per_sector_per_month: int
    payee_address: Address
    min_deal_duration_days: int
    max_deal_duration_days: int

    def __post_init__(self):
        self.organization_address = Address(self.organization_address)
        self.payee_address = Address(self.payee_address)


@utils.json_dataclass()
class SPRegistryProviderInfo(SPRegistryProvider):
    committed_bytes: int
    pending_bytes: int
    paused: bool
    blocked: bool

    @staticmethod
    def from_web3(provider_id: ActorId, data) -> "SPRegistryProviderInfo":
        if not Address(data[0]):
            raise RuntimeError("Provider not found")

        # noinspection PyArgumentList
        return SPRegistryProviderInfo(
            provider_id=ActorId(provider_id),
            organization_address=Address(data[0]),
            payee_address=Address(data[1]),
            paused=bool(data[2]),
            blocked=bool(data[3]),
            capabilities=SPRegistrySLIThresholds(
                retrievability_bps=int(data[4][0]),
                bandwidth_mbps=int(data[4][1]),
                latency_ms=int(data[4][2]),
                indexing_pct=int(data[4][3]),
            ),
            available_bytes=int(data[5]),
            committed_bytes=int(data[6]),
            pending_bytes=int(data[7]),
            price_per_sector_per_month=int(data[8]),
            min_deal_duration_days=int(data[9]),
            max_deal_duration_days=int(data[10]),
        )


class SPRegistry(ContractService):
    def __init__(self, contract_address: Address | None = None):
        super().__init__(contract_address or utils.get_env_required("SP_REGISTRY", required_type=Address),
                         os.path.dirname(os.path.realpath(__file__)) + "/abi/SPRegistry.json")

    # @notice Register a provider with full configuration in one call
    # @dev Admin convenience function for testnet onboarding. NOT in ISPRegistry interface.
    def register_provider_for(self, provider: SPRegistryProvider, from_private_key: PrivateKeyType) -> str:
        capabilities = provider.capabilities

        return self.sign_and_send_tx(
            self.contract.functions.registerProviderFor(
                provider.provider_id,
                provider.organization_address,
                (capabilities.retrievability_bps, capabilities.bandwidth_mbps, capabilities.latency_ms, capabilities.indexing_pct),
                provider.available_bytes,
                provider.price_per_sector_per_month,
                provider.payee_address,
                provider.min_deal_duration_days,
                provider.max_deal_duration_days
            ), from_private_key)

    # @notice Check if a provider is registered
    # @param provider_id The provider actor ID
    # @return True if the provider is registered
    def is_provider_registered(self, provider_id: ActorId) -> bool:
        return self.contract.functions.isProviderRegistered(provider_id).call()

    # @notice Get all registered providers
    # @return Array of all registered provider actor IDs
    def get_providers(self) -> list[ActorId]:
        return [ActorId(pid) for pid in self.contract.functions.getProviders().call()]

    def get_providers_info(self) -> list[SPRegistryProviderInfo]:
        return [self.get_provider_info(provider_id) for provider_id in self.get_providers()]

    # @notice Get full information about a provider
    # @param provider_id The provider actor ID
    # @return info The provider's registration info
    def get_provider_info(self, provider_id: ActorId) -> SPRegistryProviderInfo:
        return SPRegistryProviderInfo.from_web3(provider_id, self.contract.functions.getProviderInfo(provider_id).call())

    # @notice Get all providers registered under an organization
    # @param organization_address The organization address
    # @return Array of provider actor IDs belonging to the organization
    def get_providers_by_organization(self, organization_address: Address) -> list[ActorId]:
        return [ActorId(pid) for pid in self.contract.functions.getProvidersByOrganization(organization_address).call()]

    def get_providers_info_by_organization(self, organization_address: Address) -> list[SPRegistryProviderInfo]:
        return [self.get_provider_info(provider_id) for provider_id in self.get_providers_by_organization(organization_address)]

    # @notice Set the acceptable deal duration range for a provider
    # @param provider_id The provider to update
    # @param min_deal_duration_days Minimum deal duration in days (0 = no minimum)
    # @param max_deal_duration_days Maximum deal duration in days (0 = no maximum)
    def set_deal_duration_limits(self,
                                 provider_id: ActorId,
                                 min_deal_duration_days: int,
                                 max_deal_duration_days: int,
                                 from_private_key: PrivateKeyType) -> str:
        #
        return self.sign_and_send_tx(
            self.contract.functions.setDealDurationLimits(
                provider_id,
                min_deal_duration_days,
                max_deal_duration_days
            ), from_private_key)

    # @notice Update provider's available storage capacity
    # @param provider_id The provider to update
    # @param available_bytes New available capacity in bytes
    def update_available_space(self, provider_id: ActorId, available_bytes: int, from_private_key: PrivateKeyType) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.updateAvailableSpace(
                provider_id,
                available_bytes
            ), from_private_key)

    # @notice Set SLI capabilities for a provider
    # @param provider_id The provider to update
    # @param capabilities The SLI capabilities this provider guarantees
    def set_capabilities(self, provider_id: ActorId, capabilities: SPRegistrySLIThresholds, from_private_key: PrivateKeyType) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.setCapabilities(
                provider_id,
                (capabilities.retrievability_bps, capabilities.bandwidth_mbps, capabilities.latency_ms, capabilities.indexing_pct)
            ), from_private_key)

    # @notice Set the monthly price per sector for a provider
    # @param provider_id The provider to update
    # @param price_per_sector_per_month The monthly ERC20 token price per 32 GiB sector in smallest units (0 to disable auto-approve)
    def set_price(self, provider_id: ActorId, price_per_sector_per_month: int, from_private_key: PrivateKeyType) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.setPrice(
                provider_id,
                price_per_sector_per_month
            ), from_private_key)

    # @notice Set the payment recipient address for a provider
    # @param provider_id The provider to update
    # @param payee_address The address that will receive payments for this provider
    def set_payee(self, provider_id: ActorId, payee_address: Address, from_private_key: PrivateKeyType) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.setPayee(
                provider_id,
                payee_address
            ), from_private_key)

    # @notice Check if address is authorized to act on behalf of a provider
    # @dev Admin and OPERATOR_ROLE always return true. Otherwise checks MinerUtils.isControllingAddress.
    # @param caller Address to check
    # @param provider Provider to check against
    # @return True if caller is authorized for provider
    def is_authorized_for_provider(self, caller: Address, provider_id: ActorId) -> bool:
        return self.contract.functions.isAuthorizedForProvider(caller, provider_id).call()

    # @notice Block a provider (admin only, excluded from matching)
    # @param provider The provider to block
    def block_provider(self, provider_id: ActorId, from_private_key: PrivateKeyType) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.blockProvider(provider_id),
            from_private_key
        )

    # @notice Unblock a provider (admin only)
    # @param provider The provider to unblock
    def unblock_provider(self, provider_id: ActorId, from_private_key: PrivateKeyType) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.unblockProvider(provider_id),
            from_private_key
        )

    # @notice Pause a provider (excluded from matching)
    # @param provider The provider to pause
    def pause_provider(self, provider_id: ActorId, from_private_key: PrivateKeyType) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.pauseProvider(provider_id),
            from_private_key
        )

    # @notice Unpause a provider (available for matching)
    # @param provider The provider to unpause
    def unpause_provider(self, provider_id: ActorId, from_private_key: PrivateKeyType) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.unpauseProvider(provider_id),
            from_private_key
        )
