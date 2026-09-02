from cli.services.contract_service import ContractService, TxInfo
from cli.services.txsigner import TxSigner
from cli.services.web3_service import EthAddress, FilAddress


class ValidatorFactory(ContractService):
    _VALIDATOR_FACTORY_ADDRESS: EthAddress | None = None

    def __init__(self, contract_address: EthAddress | FilAddress | None = None):
        if not contract_address and not ValidatorFactory._VALIDATOR_FACTORY_ADDRESS:
            from cli.services.contracts.porep_market import PoRepMarket
            ValidatorFactory._VALIDATOR_FACTORY_ADDRESS = PoRepMarket().get_validator_factory_contract_address()

        # noinspection PyTypeChecker
        super().__init__(contract_address or ValidatorFactory._VALIDATOR_FACTORY_ADDRESS,
                         self.abi_dir() / "ValidatorFactory.json")

    # @notice Creates a new instance of an upgradeable contract.
    # @dev Uses BeaconProxy to create a new proxy instance, pointing to the Beacon for the logic contract.
    # @dev Reverts if an instance for the given dealId already exists.
    # @param dealId The dealId for which the proxy was created.
    def create(self, deal_id: int, signer: TxSigner) -> TxInfo:
        return self.sign_and_send_tx(self.contract.functions.create(deal_id), signer)

    # @notice Gets the instance for a given deal
    # @param dealId The ID of the deal
    # @return The instance for the given deal
    def get_instance(self, deal_id: int) -> EthAddress:
        return EthAddress(self.call_contract(self.contract.functions.getInstance(deal_id)))
