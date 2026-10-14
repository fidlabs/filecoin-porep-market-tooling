from dataclasses import dataclass

from cli.services.contract_service import ContractService
from cli.services.web3_service import ActorId, EthAddress, Web3Service


LEGACY_DEAL_COMPONENTS = [
    {"name": "id", "type": "uint256"},
    {"name": "client", "type": "address"},
    {"name": "provider", "type": "uint64"},
    {"name": "requirements", "type": "tuple", "components": [
        {"name": "retrievabilityBps", "type": "uint16"},
        {"name": "bandwidthMbps", "type": "uint16"},
        {"name": "latencyMs", "type": "uint16"},
        {"name": "indexingPct", "type": "uint8"},
    ]},
    {"name": "terms", "type": "tuple", "components": [
        {"name": "dealSizeBytes", "type": "uint256"},
        {"name": "pricePerSectorPerMonth", "type": "uint256"},
        {"name": "durationDays", "type": "uint32"},
    ]},
    {"name": "validator", "type": "address"},
    {"name": "state", "type": "uint8"},
    {"name": "railId", "type": "uint256"},
    {"name": "proposedAtBlock", "type": "uint256"},
    {"name": "manifestLocation", "type": "string"},
    {"name": "manifestHash", "type": "bytes32"},
]

LEGACY_MARKET_ABI = [
    {
        "type": "function",
        "name": "getDealProposal",
        "stateMutability": "view",
        "inputs": [{"name": "dealId", "type": "uint256"}],
        "outputs": [{
            "name": "",
            "type": "tuple",
            "components": LEGACY_DEAL_COMPONENTS,
        }],
    },
    {
        "type": "function",
        "name": "getDeals",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "deals", "type": "tuple[]", "components": LEGACY_DEAL_COMPONENTS}],
    },
    {
        "type": "function",
        "name": "getClientSmartContract",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "address"}],
    },
]

LEGACY_CLIENT_ABI = [
    {
        "type": "function",
        "name": "getClientAllocationIdsPerDeal",
        "stateMutability": "view",
        "inputs": [{"name": "dealId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "uint64[]"}],
    },
    {
        "type": "function",
        "name": "terminatedClaims",
        "stateMutability": "view",
        "inputs": [{"name": "claimId", "type": "uint64"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "type": "function",
        "name": "getSizeOfAllocations",
        "stateMutability": "view",
        "inputs": [{"name": "dealId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]


@dataclass(frozen=True)
class LegacyDeal:
    deal_id: int
    client: EthAddress
    provider: ActorId
    requirements: tuple[int, int, int, int]
    size_bytes: int
    price_per_32_gib_per_month: int
    duration_days: int
    validator: EthAddress
    state: int
    rail_id: int
    proposed_at_epoch: int
    manifest_location: str
    manifest_hash: bytes

    COMPLETED = 2
    TERMINATED = 4

    @classmethod
    def from_web3(cls, data, expected_id: int) -> "LegacyDeal":
        if int(data[0]) != expected_id:
            raise ValueError(f"Expected V1 deal {expected_id}, got {data[0]}")
        return cls(
            deal_id=int(data[0]),
            client=EthAddress(data[1]),
            provider=ActorId(data[2]),
            requirements=tuple(int(value) for value in data[3]),
            size_bytes=int(data[4][0]),
            price_per_32_gib_per_month=int(data[4][1]),
            duration_days=int(data[4][2]),
            validator=EthAddress(data[5]),
            state=int(data[6]),
            rail_id=int(data[7]),
            proposed_at_epoch=int(data[8]),
            manifest_location=str(data[9]),
            manifest_hash=bytes(data[10]),
        )


class LegacyPoRepMarket(ContractService):
    def __init__(self, address: EthAddress):
        self.web3 = Web3Service()
        self.contract = self.web3.contract(EthAddress(address), LEGACY_MARKET_ABI)

    def get_deal(self, deal_id: int) -> LegacyDeal:
        data = self.call_contract(self.contract.functions.getDealProposal(deal_id))
        return LegacyDeal.from_web3(data, deal_id)

    def get_deals(self) -> list[LegacyDeal]:
        return [LegacyDeal.from_web3(data, int(data[0])) for data in self.call_contract(self.contract.functions.getDeals())]

    def get_client_contract(self) -> "LegacyClient":
        address = EthAddress(self.call_contract(self.contract.functions.getClientSmartContract()))
        return LegacyClient(address)


class LegacyClient(ContractService):
    def __init__(self, address: EthAddress):
        self.web3 = Web3Service()
        self.contract = self.web3.contract(EthAddress(address), LEGACY_CLIENT_ABI)

    def allocation_ids(self, deal_id: int) -> list[int]:
        return [int(value) for value in self.call_contract(self.contract.functions.getClientAllocationIdsPerDeal(deal_id))]

    def allocated_size(self, deal_id: int) -> int:
        return int(self.call_contract(self.contract.functions.getSizeOfAllocations(deal_id)))

    def is_claim_terminated(self, claim_id: int) -> bool:
        return bool(self.call_contract(self.contract.functions.terminatedClaims(claim_id)))
