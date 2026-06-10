import time
from math import ceil

import click
from eth_account.datastructures import SignedMessage
from web3.auto import w3

from cli import utils
from cli.commands.client._client import client_address, client_signer
from cli.services.contracts.client_contract import ClientContract
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.porep_market import PoRepMarketDealProposal, PoRepMarketDealState, PoRepMarketDealRequest, PoRepMarket
from cli.services.contracts.usdc_token import USDCToken
from cli.services.web3_service import Web3Service


def calculate_deposit_amount_for_deal(deal: PoRepMarketDealRequest,
                                      deposit_for_months: int = 1,
                                      sector_size_bytes: int | None = None) -> int:
    assert deposit_for_months > 0

    if not sector_size_bytes:
        sector_size_bytes = PoRepMarket().get_sector_size_bytes()

    deal_size_sectors = utils.bytes_to_sectors(deal.terms.deal_size_bytes, sector_size_bytes)
    result = deal_size_sectors * deal.terms.price_per_sector_per_month * deposit_for_months

    if result != ceil(result):
        utils.confirm(f"Calculated deposit amount {result} != {ceil(result)}. Continue?", default=True, abort=True, session_id="calculated-deposit-amount")

    return ceil(result)


def get_filecoin_permit_deadline() -> int:
    return int(time.time()) + 3600  # 1 hour


# EIP-712 signing for FileCoinPay permit msg
def sign_filecoinpay_permit(amount: int, permit_deadline: int, token: USDCToken) -> SignedMessage:
    # signed_msg.signature is sensitive info, should never be logged
    signed_msg = w3.eth.account.sign_typed_data(
        domain_data={
            "name": token.name(),
            "version": "1",
            "chainId": Web3Service().get_chain_id(),
            "verifyingContract": token.address()
        },
        message_types={
            "Permit": [
                {"name": "owner", "type": "address"},
                {"name": "spender", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "nonce", "type": "uint256"},
                {"name": "deadline", "type": "uint256"},
            ]
        },
        message_data={
            "owner": client_address(),
            "spender": FileCoinPay().address(),
            "value": amount,
            "nonce": token.nonces(client_address()),
            "deadline": permit_deadline
        },
        private_key=client_signer()
    )

    if not signed_msg.v or not signed_msg.r or not signed_msg.s or not signed_msg.signature:
        raise RuntimeError("Invalid EIP-712 signature generated for FileCoinPay permit")

    click.echo(f"EIP-712 message signed for FileCoinPay permit: {utils.private_str_to_log_str(signed_msg.signature.hex())}")
    return signed_msg


def complete_deal(deal: PoRepMarketDealProposal) -> str:
    if deal.state != PoRepMarketDealState.ACCEPTED:
        raise click.ClickException(f"Deal id {deal.deal_id} is not in ACCEPTED state, current state: {deal.state}")

    check_allocations_size(deal)
    utils.confirm(f"Completing deal id {deal.deal_id}: {deal}", default=True, abort=True)

    tx_hash = PoRepMarket().complete_deal(deal.deal_id, client_signer())
    click.echo(f"Deal id {deal.deal_id} completed: {tx_hash}")

    return tx_hash


def deposit_to_filecoinpay(deposit_amount: int, token: USDCToken):
    token_decimals = token.decimals()
    token_symbol = token.symbol()

    token_balance = token.balance_of(client_address())
    token_balance_str = utils.str_from_wei(token_balance, token_decimals)

    click.echo(f"Token balance: {token_balance_str} {token_symbol}")
    click.echo()

    if token_balance < deposit_amount:
        raise click.ClickException("Insufficient token balance")

    deposit_amount_str = utils.str_from_wei(deposit_amount, token_decimals)

    utils.confirm(f"Deposit {deposit_amount_str} {token_symbol} to {client_address()} FileCoinPay account?", abort=True)
    click.echo()

    permit_deadline = get_filecoin_permit_deadline()
    signed_msg = sign_filecoinpay_permit(deposit_amount, permit_deadline, token)
    tx_hash = FileCoinPay().deposit_with_permit(token.address(),
                                                client_address(),
                                                deposit_amount,
                                                permit_deadline,
                                                signed_msg.v, utils.uint_to_bytes(signed_msg.r), utils.uint_to_bytes(signed_msg.s),
                                                client_signer())

    click.echo(f"Deposited {deposit_amount_str} {token_symbol}: {tx_hash}")


def check_allocations_size(deal: PoRepMarketDealProposal):
    final_allocation_size = ClientContract().get_size_of_allocations(deal.deal_id)
    padding = PoRepMarket().get_deal_completion_padding()
    proposed_size = deal.terms.deal_size_bytes
    delta = abs(final_allocation_size - proposed_size)

    if delta * 100 > proposed_size * padding:
        click.echo("\n[WARNING] allocated size is not in padding range! Deal completion will likely revert.")
