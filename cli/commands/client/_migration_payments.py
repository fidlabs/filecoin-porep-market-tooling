"""One-time V1-to-V2 migration payment setup."""

import click

from cli import utils
from cli.services.contracts.erc20_contract import ERC20Contract
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.txsigner import TxSigner
from cli.services.web3_service import EthAddress


def funding_shortfall(required_amount: int,
                                  token: ERC20Contract,
                                  owner: EthAddress) -> int:
    if required_amount < 0:
        raise ValueError("Required FileCoinPay funding amount cannot be negative")
    available_funds = FileCoinPay().get_account_info_if_settled(token.address(), owner).available_funds
    return max(required_amount - available_funds, 0)


def deposit_to_filecoinpay(amount: int,
                           token: ERC20Contract,
                           owner: EthAddress,
                           signer: TxSigner) -> str:
    if signer.address() != owner:
        raise click.ClickException(f"Transaction signer {signer.address()} does not match FileCoinPay account owner {owner}")
    if token.balance_of(owner) < amount:
        raise click.ClickException("Insufficient token balance")

    filecoin_pay = FileCoinPay()
    if token.allowance(owner, filecoin_pay.address()) < amount:
        token.approve(filecoin_pay.address(), amount, signer)
    return filecoin_pay.deposit(token.address(), owner, amount, signer).tx_hash


def approve_filecoinpay_operator(token: ERC20Contract,
                                 operator: EthAddress,
                                 owner: EthAddress,
                                 signer: TxSigner) -> str | None:
    if signer.address() != owner:
        raise click.ClickException(f"Transaction signer {signer.address()} does not match FileCoinPay account owner {owner}")

    filecoin_pay = FileCoinPay()
    approval = filecoin_pay.get_operator_approval(token.address(), owner, operator)
    if (approval.is_approved
            and approval.rate_allowance == utils.MAX_UINT256
            and approval.lockup_allowance == utils.MAX_UINT256
            and approval.max_lockup_period == utils.MAX_UINT256):
        return None
    return filecoin_pay.set_operator_approval(
        token.address(), operator, True, utils.MAX_UINT256, utils.MAX_UINT256, utils.MAX_UINT256, signer
    ).tx_hash
