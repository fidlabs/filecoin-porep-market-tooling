import base64
import json
import time

import click

from cli import utils
from cli.commands.client._client import client_signer
from cli.services.contracts.porep_market import PoRepMarket, PoRepMarketDealType
from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper
from cli.services.web3_service import EthAddress, Web3Service

DOMAIN_NAME = "PoRepPieceAccess"
DOMAIN_VERSION = "1"
PRIMARY_TYPE = "RetrievalVoucher"
DEFAULT_EXPIRES_IN_SECONDS = 31536000  # 365 days

RETRIEVAL_VOUCHER_TYPES = {
    PRIMARY_TYPE: [
        {"name": "grantee", "type": "address"},
        {"name": "dealId", "type": "uint256"},
        {"name": "deadline", "type": "uint256"},
    ]
}


@click.command()
@click.option("--grantee", required=True,
              help="Third-party wallet address allowed to retrieve the deal data.")
@click.option("--deal-id", type=click.IntRange(min=1), required=True,
              help="Monotonically increasing deal ID to grant retrieval access for.")
@click.option("--deadline", type=click.IntRange(min=1),
              help="Absolute Unix-second deadline for the voucher.")
@click.option("--expires-in", type=click.IntRange(min=1),
              help="Seconds until the voucher expires.  [default: 1 year]")
def sign_retrieval_voucher(grantee: str, deal_id: int, deadline: int | None, expires_in: int | None):
    """
    Sign an EIP-712 retrieval voucher granting a third-party wallet access to a deal.

    Prints the raw voucher token: base64url-nopad (compact JSON of typed-data + signature).
    """

    if deadline is not None and expires_in is not None:
        raise click.ClickException("Use either --deadline or --expires-in, not both")

    grantee_address = EthAddress.from_any(grantee)
    now = int(time.time())

    if deadline is not None:
        resolved_deadline = deadline
    else:
        resolved_deadline = now + (expires_in if expires_in is not None else DEFAULT_EXPIRES_IN_SECONDS)

    if resolved_deadline <= now:
        raise click.ClickException(f"Deadline {resolved_deadline} is not in the future (now={now})")

    deal = PoRepMarketViewHelper().get_deal_view(deal_id).deal
    signer = client_signer()
    signer_address = signer.address()

    if deal.deal_type != PoRepMarketDealType.PRIVATE:
        raise click.ClickException(
            f"Deal ID {deal_id} is {deal.deal_type}, not PRIVATE; "
            f"retrieval vouchers are only valid for private deals"
        )

    if deal.client_address != signer_address:
        raise click.ClickException(
            f"Deal ID {deal_id} client address {deal.client_address} "
            f"does not match signing wallet {signer_address}"
        )

    domain_data = {
        "name": DOMAIN_NAME,
        "version": DOMAIN_VERSION,
        "chainId": Web3Service().get_chain_id(),
        "verifyingContract": str(PoRepMarket().address()),
    }
    message_data = {
        "grantee": str(grantee_address),
        "dealId": deal_id,
        "deadline": resolved_deadline,
    }

    utils.confirm(
        f"Sign retrieval voucher?\n"
        f"  grantee:  {grantee_address}\n"
        f"  dealId:   {deal_id}\n"
        f"  deadline: {resolved_deadline}\n"
        f"  domain:   {DOMAIN_NAME} v{DOMAIN_VERSION} "
        f"chainId={domain_data['chainId']} verifyingContract={domain_data['verifyingContract']}",
        default=True,
        abort=True,
    )

    signed_msg = signer.sign_typed_data(
        domain_data=domain_data,
        message_types=RETRIEVAL_VOUCHER_TYPES,
        message_data=message_data,
    )

    if not signed_msg.v or not signed_msg.r or not signed_msg.s or not signed_msg.signature:
        raise RuntimeError("Invalid EIP-712 signature generated for retrieval voucher")

    signature_hex = signed_msg.signature.hex()
    if not signature_hex.startswith("0x"):
        signature_hex = "0x" + signature_hex

    token = {
        "domain": domain_data,
        "types": RETRIEVAL_VOUCHER_TYPES,
        "primaryType": PRIMARY_TYPE,
        "message": message_data,
        "signature": signature_hex,
    }

    # Compact JSON + base64url (no pad) voucher token
    token_bytes = json.dumps(token, separators=(",", ":"), sort_keys=True).encode()
    voucher_token = base64.urlsafe_b64encode(token_bytes).rstrip(b"=").decode()

    click.echo(f"EIP-712 retrieval voucher signed: {utils.private_str_to_log_str(signature_hex)}")
    click.echo(voucher_token)
