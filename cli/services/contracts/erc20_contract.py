from pathlib import Path

from cli.services.contract_service import ContractService
from cli.services.web3_service import EthAddress


class ERC20Contract(ContractService):
    def __init__(self, contract_address: EthAddress, contract_abi_path: Path | None = None):
        super().__init__(contract_address, contract_abi_path or (self.abi_dir() / "ERC20.json"))

    def balance_of(self, account: EthAddress) -> int:
        return self.call_contract(self.contract.functions.balanceOf(account))

    def decimals(self) -> int:
        return self.call_contract(self.contract.functions.decimals())

    def name(self) -> str:
        return self.call_contract(self.contract.functions.name())

    def symbol(self) -> str:
        return self.call_contract(self.contract.functions.symbol())
