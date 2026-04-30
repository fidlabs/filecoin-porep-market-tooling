import os

from eth_account.types import PrivateKeyType

from cli.services.contracts.contract_service import ContractService
from cli.services.web3_service import Address


class FileCoinPayValidator(ContractService):
    def __init__(self, contract_address: Address):
        super().__init__(contract_address,
                         os.path.dirname(os.path.realpath(__file__)) + '/abi/Validator.json')

    # @notice Creates a payment rail with the specified parameters and set initial lockup period
    # @dev Only callable by the client
    # @dev Sets railID in contract state and updates the PoRepMarket with the created rail ID
    # @param token The ERC20 token to use for the payment rail
    def create_rail(self, token_address: Address, from_private_key: PrivateKeyType) -> str:
        return self.sign_and_send_tx(self.contract.functions.createRail(token_address), from_private_key)

    # @notice Disables future payments for a payment rail by terminating the rail
    # @dev Only callable by POREP_SERVICE bot
    # @dev After calling this method, the lockup period cannot be changed, and the rail's rate and fixed lockup may only be reduced
    # @param railId The ID of the rail to terminate
    def disable_future_rail_payments(self, rail_id: int, from_private_key: PrivateKeyType) -> str:
        return self.sign_and_send_tx(self.contract.functions.disableFutureRailPayments(rail_id), from_private_key)
