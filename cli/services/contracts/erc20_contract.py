from pathlib import Path

from cli.services.contracts.contract_service import ContractService
from cli.services.web3_service import EthAddress


class ERC20Contract(ContractService):
    def __init__(self, contract_address: EthAddress, contract_abi_path: Path | None = None):
        super().__init__(contract_address,
                         contract_abi_path or (self.abi_dir() / "ERC20.json"))

    def balance_of(self, account: EthAddress) -> int:
        return self.contract.functions.balanceOf(account).call()

    def decimals(self) -> int:
        return self.contract.functions.decimals().call()

    def name(self) -> str:
        return self.contract.functions.name().call()

    def symbol(self) -> str:
        return self.contract.functions.symbol().call()
