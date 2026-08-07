from cli.services.contract_service import ContractService
from cli.services.txsigner import TxSigner
from cli.services.web3_service import EthAddress, FilAddress


class AccessControlUpgradeable(ContractService):
    def __init__(self, contract_address: EthAddress | FilAddress):
        super().__init__(contract_address, self.abi_dir() / "AccessControlUpgradeable.json")

    # @dev Grants `role` to `account`.
    # If `account` had not been already granted `role`, emits a {RoleGranted} event.
    # Requirements:
    # - the caller must have ``role``'s admin role.
    # May emit a {RoleGranted} event.
    def grant_role(self, role: bytes, account: EthAddress, signer: TxSigner) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.grantRole(role, account),
            signer
        )

    # @dev Returns `true` if `account` has been granted `role`.
    def has_role(self, role: bytes, account: EthAddress) -> bool:
        return self.call_contract(self.contract.functions.hasRole(role, account))
