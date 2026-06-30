from cli.services.contracts.contract_service import ContractService
from cli.services.contracts.types.rail import RailStatus
from cli.services.txsigner import TxSigner
from cli.services.web3_service import EthAddress


class FileCoinPayValidator(ContractService):
    def __init__(self, contract_address: EthAddress):
        super().__init__(contract_address,
                         self.abi_dir() / "Validator.json")

    # @notice Creates a payment rail with the specified parameters and set initial lockup period
    # @dev Only callable by the client
    # @dev Sets railID in contract state and updates the PoRepMarket with the created rail ID
    # @param token The ERC20 token to use for the payment rail
    def create_rail(self, token_address: EthAddress, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.createRail(token_address), signer)

    # @notice Terminates the payment rail before the service window ends
    # @dev Only callable by POREP_SERVICE_ROLE
    def early_rail_termination(self, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.earlyRailTermination(), signer)

    # @notice Finalizes the deal after the service window has ended, terminating the rail
    def finalize_deal(self, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.finalizeDeal(), signer)

    # @notice Getter for the current rail status
    # @return status The rail status (NONE=0, PREPARED=10, ACTIVE=20, TERMINATED=100)
    def get_rail_status(self) -> RailStatus:
        return RailStatus(self.contract.functions.getRailStatus().call())

    # @notice Updates the payment rate on the rail
    # @dev Only callable by POREP_SERVICE_ROLE
    # @param newRate The new payment rate per epoch
    def modify_rail_payment(self, new_rate: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.modifyRailPayment(new_rate), signer)
