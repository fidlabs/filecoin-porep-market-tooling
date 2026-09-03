from cli import utils
from cli.services.contracts.erc20_contract import ERC20Contract
from cli.services.web3_service import EthAddress, FilAddress


class USDCToken(ERC20Contract):
    def __init__(self, contract_address: EthAddress | FilAddress | None = None):
        super().__init__(contract_address or utils.get_env_required("USDC_TOKEN", required_type=EthAddress.from_any),
                         self.abi_dir() / "USDC.json")

    def nonces(self, account: EthAddress) -> int:
        return self.call_contract(self.contract.functions.nonces(account))
