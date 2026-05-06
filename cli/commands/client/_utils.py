import time
from math import ceil

import click
from eth_account.datastructures import SignedMessage
from web3.auto import w3

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.client._client import client_address, client_private_key
from cli.services.contracts.porep_market import PoRepMarketDealProposal, PoRepMarketDealState, PoRepMarketDealRequest
from cli.services.contracts.usdc_token import USDCToken
from cli.services.web3_service import EthAddress
from cli.services.web3_service import Web3Service


def get_client_deals(state: PoRepMarketDealState | None = None) -> list[PoRepMarketDealProposal]:
    all_deals = commands_utils.get_all_deals(state=state)
    return [deal for deal in all_deals if deal.client_address == client_address()]


def calculate_deposit_amount_for_deal(deal: PoRepMarketDealRequest, deposit_for_months: int = 1) -> int:
    if deposit_for_months < 0:
        raise RuntimeError("deposit_for_months must be >= 0")

    deal_size_sectors = commands_utils.bytes_to_sectors(deal.terms.deal_size_bytes)
    result = deal_size_sectors * deal.terms.price_per_sector_per_month * deposit_for_months

    if result != ceil(result):
        click.confirm(f"Calculated deposit amount {result} != {ceil(result)}. Continue?", default=True, abort=True)

    return ceil(result)


def get_permit_deadline() -> int:
    return int(time.time()) + 3600  # 1 hour


# EIP-712 signing for FileCoinPay permit msg
def sign_filecoinpay_permit(amount: int, permit_deadline: int) -> SignedMessage:
    token_name = USDCToken().name()

    # signed_msg.signature is sensitive info, should never be logged
    signed_msg = w3.eth.account.sign_typed_data(
        domain_data={
            "name": token_name,
            "version": "1",
            "chainId": Web3Service().get_chain_id(),
            "verifyingContract": utils.get_env_required("USDC_TOKEN", required_type=EthAddress)
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
            "spender": utils.get_env_required("FILECOIN_PAY", required_type=EthAddress),
            "value": amount,
            "nonce": USDCToken().nonces(client_address()),
            "deadline": permit_deadline
        },
        private_key=client_private_key()
    )

    if not signed_msg.v or not signed_msg.r or not signed_msg.s or not signed_msg.signature:
        raise RuntimeError("Invalid EIP-712 signature generated for FileCoinPay permit")

    click.echo(f"EIP-712 message signed for FileCoinPay permit: {utils.private_str_to_log_str(signed_msg.signature.hex())}")
    return signed_msg
