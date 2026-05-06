import os

from eth_account.types import PrivateKeyType

from cli import utils
from cli.services.contracts.contract_service import ContractService
from cli.services.web3_service import EthAddress


class ValidatorFactory(ContractService):
    def __init__(self, contract_address: EthAddress | None = None):
        super().__init__(contract_address or utils.get_env_required('VALIDATOR_FACTORY', required_type=EthAddress),
                         os.path.dirname(os.path.realpath(__file__)) + '/abi/ValidatorFactory.json')

    # @notice Creates a new instance of an upgradeable contract.
    # @dev Uses BeaconProxy to create a new proxy instance, pointing to the Beacon for the logic contract.
    # @dev Reverts if an instance for the given dealId already exists.
    # @param dealId The dealId for which the proxy was created.
    def create(self, deal_id: int, from_private_key: PrivateKeyType) -> str:
        return self.sign_and_send_tx(self.contract.functions.create(deal_id), from_private_key)

    # @notice Gets the instance for a given deal
    # @param dealId The ID of the deal
    # @return The instance for the given deal
    def get_instance(self, deal_id: int) -> EthAddress:
        return EthAddress(self.contract.functions.getInstance(deal_id).call())
