from eth_account.types import PrivateKeyType

from cli.services.contracts.contract_service import ContractService
from cli.services.web3_service import EthAddress


class FileCoinPayValidator(ContractService):
    def __init__(self, contract_address: EthAddress):
        super().__init__(contract_address,
                         self.abi_dir() / "Validator.json")

    # @notice Creates a payment rail with the specified parameters and set initial lockup period
    # @dev Only callable by the client
    # @dev Sets railID in contract state and updates the PoRepMarket with the created rail ID
    # @param token The ERC20 token to use for the payment rail
    def create_rail(self, token_address: EthAddress, from_private_key: PrivateKeyType) -> str:
        return self.sign_and_send_tx(self.contract.functions.createRail(token_address), from_private_key)

    # @notice Terminates a payment rail, preventing further payments after the rail's lockup period.
    #         After calling this method, the lockup period cannot be changed, and the rail's rate and fixed lockup may only be reduced.
    # @param railId The ID of the rail to terminate.
    def terminate_rail(self, rail_id: int, from_private_key: PrivateKeyType) -> str:
        return self.sign_and_send_tx(self.contract.functions.terminateRail(rail_id), from_private_key)
