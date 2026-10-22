from pathlib import Path

from cli.services.contract_service import ContractService, TxInfo
from cli.services.txsigner import TxSigner
from cli.services.web3_service import EthAddress, FilAddress


class ERC20Contract(ContractService):
    def __init__(self, contract_address: EthAddress | FilAddress, contract_abi_path: Path | None = None):
        super().__init__(contract_address, contract_abi_path or (self.abi_dir() / "ERC20.json"))

    def balance_of(self, account: EthAddress) -> int:
        return self.call_contract(self.contract.functions.balanceOf(account))

    def decimals(self) -> int:
        return self.call_contract(self.contract.functions.decimals())

    def name(self) -> str:
        return self.call_contract(self.contract.functions.name())

    def symbol(self) -> str:
        return self.call_contract(self.contract.functions.symbol())

    def allowance(self, owner: EthAddress, spender: EthAddress) -> int:
        return self.call_contract(self.contract.functions.allowance(owner, spender))

    def approve(self, spender: EthAddress, amount: int, signer: TxSigner) -> TxInfo:
        return self.sign_and_send_tx(self.contract.functions.approve(spender, amount), signer)
