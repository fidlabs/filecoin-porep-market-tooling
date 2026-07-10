import enum

from cli.services.contract_service import ContractService
from cli.services.txsigner import TxSigner
from cli.services.web3_service import EthAddress


# @title RailStatus
# @notice Defines status codes for a FilecoinPay rail lifecycle
class FileCoinPayRailStatus(enum.Enum):
    NONE = 0  # Rail is authorized and ready, but payment cannot accrue until storage activates.
    PREPARED = 10
    ACTIVE = 20
    TERMINATED = 100  # FilecoinPay rail termination has been observed by Validator and settlement is capped at earlyTerminatedEpoch.

    @staticmethod
    def from_web3(s: str | int | None) -> "FileCoinPayRailStatus":
        if not s:
            raise ValueError("Rail status string cannot be None")

        s = str(s).strip().lower()

        if s in ("0", "none"):
            return FileCoinPayRailStatus.NONE
        elif s in ("10", "prepared"):
            return FileCoinPayRailStatus.PREPARED
        elif s in ("20", "active"):
            return FileCoinPayRailStatus.ACTIVE
        elif s in ("100", "terminated"):
            return FileCoinPayRailStatus.TERMINATED
        else:
            raise ValueError(f"Invalid rail status: {s}")

    @staticmethod
    def to_string_list():
        return [status.name for status in FileCoinPayRailStatus]

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


class FileCoinPayValidator(ContractService):
    def __init__(self, contract_address: EthAddress):
        super().__init__(contract_address, self.abi_dir() / "Validator.json")

    # @notice Creates the FilecoinPay rail for this validator and sets the initial lockup period.
    # @dev Only callable by the client.
    # @dev Sets railID in contract state and updates the PoRepMarket with the created rail ID.
    def create_rail(self, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.createRail(), signer)

    # @notice Terminates a payment rail early and terminates its deal
    # @dev Only callable by POREP_SERVICE bot
    def early_rail_termination(self, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.earlyRailTermination(), signer)

    # @notice Finalizes the deal after the service window has ended, terminating the rail
    def finalize_deal(self, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.finalizeDeal(), signer)

    # @notice Retrieves the current status of the payment rail
    # @return railStatus Current status of the payment rail
    def get_rail_status(self) -> FileCoinPayRailStatus:
        return FileCoinPayRailStatus.from_web3(self.contract.functions.getRailStatus().call())

    # @notice Modifies the payment rate
    # @dev Only callable by the PoRepMarket contract
    # @param newRate The new payment rate per epoch
    def modify_rail_payment(self, new_rate: int, signer: TxSigner) -> str:
        return self.sign_and_send_tx(self.contract.functions.modifyRailPayment(new_rate), signer)
