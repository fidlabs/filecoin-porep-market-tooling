import click

from cli import utils
from cli.commands.client._client import client_address, client_signer
from cli.services.contracts.datacap_evidence_adapter import DataCapEvidenceAdapter
from cli.services.contracts.erc20_contract import ERC20Contract
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.porep_market import (
    PoRepMarket,
    PoRepMarketDeal,
    PoRepMarketDealState,
)
from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper
from cli.services.txsigner import TxSigner
from cli.services.web3_service import EthAddress


@utils.json_dataclass()
class FileCoinPayFundingQuote:
    required_amount: int
    available_funds: int
    deposit_amount: int


def get_filecoinpay_funding_quote(required_amount: int,
                                  token: ERC20Contract,
                                  owner: EthAddress) -> FileCoinPayFundingQuote:
    if required_amount < 0:
        raise ValueError("Required FileCoinPay funding amount cannot be negative")

    account = FileCoinPay().get_account_info_if_settled(token.address(), owner)
    available_funds = account.available_funds
    return FileCoinPayFundingQuote(
        required_amount=required_amount,
        available_funds=available_funds,
        deposit_amount=max(required_amount - available_funds, 0),
    )


def finish_datacap_posting(deal: PoRepMarketDeal) -> str:
    if deal.state != PoRepMarketDealState.ACCEPTED:
        raise click.ClickException(f"Deal id {deal.deal_id} is not in ACCEPTED state, current state: {deal.state}")

    check_allocations_size(deal.deal_id)
    utils.confirm(f"Finishing DataCap posting for deal id {deal.deal_id} (blocks further allocation batches)", default=True, abort=True)

    tx_hash = DataCapEvidenceAdapter(deal.evidence_adapter_address).finish_datacap_posting(deal.deal_id, client_signer()).tx_hash
    click.echo(f"DataCap posting for deal id {deal.deal_id} finished: {tx_hash}")

    return tx_hash


def deposit_to_filecoinpay(deposit_amount: int,
                           token: ERC20Contract,
                           owner: EthAddress | None = None,
                           signer: TxSigner | None = None,
                           prompt: bool = True) -> str:
    owner = owner or client_address()
    signer = signer or client_signer()

    if signer.address() != owner:
        raise click.ClickException(f"Transaction signer {signer.address()} does not match FileCoinPay account owner {owner}")

    token_decimals = token.decimals()
    token_symbol = token.symbol()

    token_balance = token.balance_of(owner)
    token_balance_str = utils.str_from_wei(token_balance, token_decimals)

    click.echo(f"Token balance: {token_balance_str} {token_symbol}")
    click.echo()

    if token_balance < deposit_amount:
        raise click.ClickException("Insufficient token balance")

    deposit_amount_str = utils.str_from_wei(deposit_amount, token_decimals)

    if prompt:
        utils.confirm(f"Deposit {deposit_amount_str} {token_symbol} to {owner} FileCoinPay account?", abort=True)
        click.echo()

    filecoin_pay = FileCoinPay()
    allowance = token.allowance(owner, filecoin_pay.address())

    if allowance < deposit_amount:
        approve_tx_hash = token.approve(filecoin_pay.address(), deposit_amount, signer).tx_hash
        click.echo(f"Approved FileCoinPay to spend {deposit_amount_str} {token_symbol}: {approve_tx_hash}")

    tx_hash = filecoin_pay.deposit(token.address(), owner, deposit_amount, signer).tx_hash

    click.echo(f"Deposited {deposit_amount_str} {token_symbol}: {tx_hash}")
    return tx_hash


def approve_filecoinpay_operator(token: ERC20Contract,
                                 operator: EthAddress,
                                 owner: EthAddress,
                                 signer: TxSigner,
                                 rate_allowance: int = utils.MAX_UINT256,
                                 lockup_allowance: int = utils.MAX_UINT256,
                                 max_lockup_period: int = utils.MAX_UINT256,
                                 prompt: bool = True) -> str | None:
    if signer.address() != owner:
        raise click.ClickException(f"Transaction signer {signer.address()} does not match FileCoinPay account owner {owner}")

    filecoin_pay = FileCoinPay()
    approval = filecoin_pay.get_operator_approval(token.address(), owner, operator)

    if (approval.is_approved and
            approval.rate_allowance == rate_allowance and
            approval.lockup_allowance == lockup_allowance and
            approval.max_lockup_period == max_lockup_period):
        click.echo(f"Operator already approved: {operator}")
        return None

    if prompt:
        utils.confirm(
            f"Approve FileCoinPay operator {operator} for {token.symbol()}?\n"
            f"  Rate allowance: {'MAX_UINT256' if rate_allowance == utils.MAX_UINT256 else rate_allowance}\n"
            f"  Lockup allowance: {'MAX_UINT256' if lockup_allowance == utils.MAX_UINT256 else lockup_allowance}\n"
            f"  Max lockup period: {'MAX_UINT256' if max_lockup_period == utils.MAX_UINT256 else max_lockup_period}",
            abort=True,
        )
        click.echo()

    tx_hash = filecoin_pay.set_operator_approval(
        token.address(),
        operator,
        True,
        rate_allowance,
        lockup_allowance,
        max_lockup_period,
        signer,
    ).tx_hash
    click.echo(f"Approved FileCoinPay operator {operator}: {tx_hash}")
    return tx_hash


def check_allocations_size(deal_id: int):
    deal = PoRepMarketViewHelper().get_deal_view(deal_id)
    final_allocation_size = DataCapEvidenceAdapter(deal.deal.evidence_adapter_address).get_allocated_bytes(deal_id)
    padding = PoRepMarket().get_deal_activation_padding()
    proposed_size = deal.terms.requested_size_bytes
    delta = abs(final_allocation_size - proposed_size)

    if delta * 100 > proposed_size * padding:
        click.echo("\n[WARNING] allocated size is not in padding range! Deal activation will likely revert.")
