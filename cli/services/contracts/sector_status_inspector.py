from cli import utils
from cli.services.contract_service import ContractService
from cli.services.web3_service import EthAddress, FilAddress


class SectorStatusInspector(ContractService):
    ACTIVE = 1

    def __init__(self, address: EthAddress | FilAddress | None = None):
        super().__init__(
            address or utils.get_env_required(
                "POREP_MARKET_SECTOR_STATUS_INSPECTOR", required_type=EthAddress.from_any
            ),
            self.abi_dir() / "PoRepMarketSectorStatusInspector.json",
        )

    def porep_market_contract(self) -> EthAddress:
        return EthAddress(self.call_contract(self.contract.functions.POREPMARKET_CONTRACT()))

    def is_active(self, deal_id: int, sector: int, deadline: int, partition: int) -> bool:
        return bool(self.call_contract(
            self.contract.functions.validateSectorStatus(
                deal_id, sector, self.ACTIVE, deadline, partition
            )
        ))
