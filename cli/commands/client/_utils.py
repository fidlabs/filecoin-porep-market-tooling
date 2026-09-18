import time

import click
from eth_account.datastructures import SignedMessage

from cli import utils
from cli.commands.client._client import client_address, client_signer
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.usdc_token import USDCToken
from cli.services.web3_service import Web3Service


def get_filecoin_permit_deadline() -> int:
    return int(time.time()) + 3600  # 1 hour


# EIP-712 signing for FileCoinPay permit msg
def sign_filecoinpay_permit(amount: int, permit_deadline: int, token: USDCToken) -> SignedMessage:
    # signed_msg.signature is sensitive info, should never be logged
    signed_msg = client_signer().sign_typed_data(
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
        }
    )

    if not signed_msg.v or not signed_msg.r or not signed_msg.s or not signed_msg.signature:
        raise RuntimeError("Invalid EIP-712 signature generated for FileCoinPay permit")

    click.echo(f"EIP-712 message signed for FileCoinPay permit: {utils.private_str_to_log_str(signed_msg.signature.hex())}")
    return signed_msg


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
                                                client_signer()).tx_hash

    click.echo(f"Deposited {deposit_amount_str} {token_symbol}: {tx_hash}")
