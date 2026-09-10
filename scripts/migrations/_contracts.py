import logging

from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.legacy_porep_market import LEGACY_VALIDATOR_ABI, LegacyValidator
from cli.services.web3_service import EthAddress, Web3Service


LEGACY_VALIDATOR_WRITE_ABI = [
    {
        "type": "function",
        "name": "setMinEpochsBetweenSettlements",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "minEpochs", "type": "uint256"}],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "updateLockupPeriod",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "newLockupPeriod", "type": "uint256"}],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "disableFutureRailPayments",
        "stateMutability": "nonpayable",
        "inputs": [],
        "outputs": [],
    },
]


class OperationalLegacyValidator(LegacyValidator):
    def __init__(self, address: EthAddress):
        self.logger = logging.getLogger(self._get_class_name())
        self.web3 = Web3Service()
        self.contract = self.web3.contract(EthAddress(address), LEGACY_VALIDATOR_ABI + LEGACY_VALIDATOR_WRITE_ABI)

    def set_min_epochs_between_settlements(self, epochs: int, signer):
        return self.sign_and_send_tx(self.contract.functions.setMinEpochsBetweenSettlements(epochs), signer)

    def update_lockup_period(self, epochs: int, signer):
        return self.sign_and_send_tx(self.contract.functions.updateLockupPeriod(epochs), signer)

    def disable_future_rail_payments(self, signer):
        return self.sign_and_send_tx(self.contract.functions.disableFutureRailPayments(), signer)


class OperationalFileCoinPay(FileCoinPay):
    def settle_rail(self, rail_id: int, until_epoch: int, signer):
        return self.sign_and_send_tx(self.contract.functions.settleRail(rail_id, until_epoch), signer)
