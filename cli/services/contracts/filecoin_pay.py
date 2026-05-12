from eth_account.types import PrivateKeyType

from cli import utils
from cli.services.contracts.contract_service import ContractService
from cli.services.web3_service import EthAddress


@utils.json_dataclass()
class FileCoinPayAccount:
    funds: int
    lockup_current: int
    lockup_rate: int
    lockup_last_settled_at: int  # epoch up to and including which lockup has been settled for the account

    @staticmethod
    def from_web3(data) -> "FileCoinPayAccount":
        # noinspection PyArgumentList
        return FileCoinPayAccount(
            funds=int(data[0]),
            lockup_current=int(data[1]),
            lockup_rate=int(data[2]),
            lockup_last_settled_at=int(data[3])
        )


@utils.json_dataclass()
class FileCoinPayOperatorApproval:
    is_approved: bool
    rate_allowance: int
    lockup_allowance: int
    rate_usage: int
    lockup_usage: int
    max_lockup_period: int

    @staticmethod
    def from_web3(data) -> "FileCoinPayOperatorApproval":
        # noinspection PyArgumentList
        return FileCoinPayOperatorApproval(
            is_approved=bool(data[0]),
            rate_allowance=int(data[1]),
            lockup_allowance=int(data[2]),
            rate_usage=int(data[3]),
            lockup_usage=int(data[4]),
            max_lockup_period=int(data[5])
        )


class FileCoinPay(ContractService):
    def __init__(self, contract_address: EthAddress | None = None):
        super().__init__(contract_address or utils.get_env_required("FILECOIN_PAY", required_type=EthAddress),
                         self.abi_dir() / "FileCoinPay.json")

    # @notice Deposits tokens using permit (EIP-2612) approval in a single transaction,
    #         while also setting operator approval.
    # @param token The ERC20 token address to deposit and for which the operator approval is being set.
    #             Note: The token must support EIP-2612 permit functionality.
    # @param to The address whose account will be credited (must be the permit signer).
    # @param amount The amount of tokens to deposit.
    # @param deadline Permit deadline (timestamp).
    # @param v,r,s Permit signature.
    # @param operator The address of the operator whose approval is being modified.
    # @param rate_allowance The maximum payment rate the operator can set across all rails created by the operator
    #             on behalf of the message sender. If this is less than the current payment rate, the operator will
    #             only be able to reduce rates until they fall below the target.
    # @param lockup_allowance The maximum amount of funds the operator can lock up on behalf of the message sender
    #             towards future payments. If this exceeds the current total amount of funds locked towards future payments,
    #             the operator will only be able to reduce future lockup.
    # @param max_lockup_period The maximum number of epochs (blocks) the operator can lock funds for. If this is less than
    #             the current lockup period for a rail, the operator will only be able to reduce the lockup period.
    def deposit_with_permit_and_approve_operator(self,
                                                 token: EthAddress,
                                                 to: EthAddress,
                                                 amount: int,
                                                 deadline: int,
                                                 v: int, r: bytes, s: bytes,
                                                 operator: EthAddress,
                                                 rate_allowance: int,
                                                 lockup_allowance: int,
                                                 max_lockup_period: int,
                                                 from_private_key: PrivateKeyType) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.depositWithPermitAndApproveOperator(
                token, to, amount, deadline, v, r, s, operator, rate_allowance, lockup_allowance, max_lockup_period
            ), from_private_key)

    # @notice Deposits tokens using permit (EIP-2612) approval in a single transaction,
    #         while also increasing operator approval allowances.
    # @param token The ERC20 token address to deposit and for which the operator approval is being increased.
    #             Note: The token must support EIP-2612 permit functionality.
    # @param to The address whose account will be credited (must be the permit signer).
    # @param amount The amount of tokens to deposit.
    # @param deadline Permit deadline (timestamp).
    # @param v,r,s Permit signature.
    # @param operator The address of the operator whose allowances are being increased.
    # @param rate_allowance_increase The amount to increase the rate allowance by.
    # @param lockup_allowance_increase The amount to increase the lockup allowance by.
    # @custom:constraint Operator must already be approved.
    def deposit_with_permit_and_increase_operator_approval(self,
                                                           token: EthAddress,
                                                           to: EthAddress,
                                                           amount: int,
                                                           deadline: int,
                                                           v: int, r: bytes, s: bytes,
                                                           operator: EthAddress,
                                                           rate_allowance_increase: int,
                                                           lockup_allowance_increase: int,
                                                           from_private_key: PrivateKeyType) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.depositWithPermitAndIncreaseOperatorApproval(
                token, to, amount, deadline, v, r, s, operator, rate_allowance_increase, lockup_allowance_increase
            ), from_private_key)

    # @notice Deposits tokens using permit (EIP-2612) approval in a single transaction.
    # @param token The ERC20 token address to deposit.
    # @param to The address whose account will be credited (must be the permit signer).
    # @param amount The amount of tokens to deposit.
    # @param deadline Permit deadline (timestamp).
    # @param v,r,s Permit signature.
    def deposit_with_permit(self,
                            token: EthAddress,
                            to: EthAddress,
                            amount: int,
                            deadline: int,
                            v: int, r: bytes, s: bytes,
                            from_private_key: PrivateKeyType) -> str:
        return self.sign_and_send_tx(
            self.contract.functions.depositWithPermit(
                token, to, amount, deadline, v, r, s
            ), from_private_key)

    # token => client => operator => Approval
    def get_operator_approval(self, token: EthAddress, client: EthAddress, operator: EthAddress) -> FileCoinPayOperatorApproval:
        return FileCoinPayOperatorApproval.from_web3(self.contract.functions.operatorApprovals(token, client, operator).call())

    # Internal balances
    # The self-balance collects network fees
    def get_account(self, token: EthAddress, owner: EthAddress) -> FileCoinPayAccount:
        return FileCoinPayAccount.from_web3(self.contract.functions.accounts(token, owner).call())
