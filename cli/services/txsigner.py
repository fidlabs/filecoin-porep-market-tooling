import rlp
from eth_account._utils.legacy_transactions import (
    Transaction, encode_transaction, serializable_unsigned_transaction_from_dict,
)
from eth_account.datastructures import SignedMessage, SignedTransaction
from eth_account.messages import encode_typed_data, SignableMessage
from eth_account.typed_transactions import TypedTransaction
from eth_account.typed_transactions.dynamic_fee_transaction import transaction_rpc_to_rlp_structure
from eth_account.types import PrivateKeyType
from eth_utils import keccak
from eth_utils.toolz import dissoc
from hexbytes import HexBytes

from cli.services.web3_service import EthAddress, FilAddress, Web3Service


class TxSigner:
    """
    Blockchain transaction signing strategy used by the CLI.

    Implementations expose a stable EVM address and encapsulate one concrete
    way of signing transactions and EIP-712 typed data.
    """

    def address(self) -> EthAddress:
        pass

    def sign_transaction(self, tx_params: dict) -> SignedTransaction:
        pass

    def sign_typed_data(self, domain_data: dict, message_types: dict, message_data: dict) -> SignedMessage:
        pass


class PrivateKeyTxSigner(TxSigner):
    """
    Signs payloads with a raw EVM private key loaded in-process.
    """

    def __init__(self, private_key: PrivateKeyType):
        self.private_key = private_key
        self._address = EthAddress.from_private_key(private_key)

    def address(self) -> EthAddress:
        return self._address

    def sign_transaction(self, tx_params: dict) -> SignedTransaction:
        return Web3Service().w3().eth.account.sign_transaction(tx_params, self.private_key)

    def sign_typed_data(self, domain_data: dict, message_types: dict, message_data: dict) -> SignedMessage:
        return Web3Service().w3().eth.account.sign_typed_data(
            domain_data=domain_data,
            message_types=message_types,
            message_data=message_data,
            private_key=self.private_key,
        )


class LotusWalletTxSigner(TxSigner):
    """
    Signs FEVM payloads via Filecoin.WalletSign exposed by the RPC node.

    The private key never leaves Lotus-compatible wallet infrastructure. The CLI
    sends raw unsigned transaction bytes or raw EIP-712 preimage bytes and lets
    WalletSign apply the delegated-address signing flow internally.

    This signer is valid only for delegated f410/t410 wallets. The RPC
    endpoint behind RPC_URL must expose both standard EVM JSON-RPC methods
    and the Filecoin-specific Filecoin.WalletSign method.
    """

    def __init__(self, wallet_address: str, lotus_token: str):
        self.fil_address = FilAddress.from_any(wallet_address)
        self.eth_address = EthAddress.from_any(wallet_address)
        self.lotus_token = lotus_token

    def address(self) -> EthAddress:
        return self.eth_address

    @staticmethod
    def _parse_rsv(sig: bytes) -> tuple[int, int, int]:
        """
        Split a 65-byte delegated signature into r, s and recovery id.
        """

        return (int.from_bytes(sig[:32], "big"),
                int.from_bytes(sig[32:64], "big"),
                sig[64])

    def _validate_recovered_transaction(self, raw_transaction: HexBytes):
        recovered = EthAddress(Web3Service().w3().eth.account.recover_transaction(raw_transaction))

        if recovered != self.eth_address:
            raise RuntimeError(f"Lotus signed transaction with unexpected address: recovered={recovered}, expected={self.eth_address}")

    def _validate_recovered_typed_data(self, signable_message: SignableMessage, signature: HexBytes):
        recovered = EthAddress(Web3Service().w3().eth.account.recover_message(signable_message, signature=signature))

        if recovered != self.eth_address:
            raise RuntimeError(f"Lotus signed typed data with unexpected address: recovered={recovered}, expected={self.eth_address}")

    @staticmethod
    def _unsigned_tx_to_raw_bytes(unsigned_tx) -> bytes:
        """
        Serialize an unsigned transaction exactly as Lotus expects before signing.
        """

        if isinstance(unsigned_tx, TypedTransaction):
            inner = unsigned_tx.transaction
            tx_no_sig = dissoc(inner.dictionary, "v", "r", "s")
            rlp_struct = transaction_rpc_to_rlp_structure(tx_no_sig)
            serializer = inner.__class__._unsigned_transaction_serializer
            return bytes([inner.__class__.transaction_type]) + rlp.encode(serializer.from_dict(rlp_struct))
        elif isinstance(unsigned_tx, Transaction):
            return encode_transaction(unsigned_tx, vrs=(unsigned_tx.v, 0, 0))
        else:
            return rlp.encode(unsigned_tx)

    @staticmethod
    def compute_v(unsigned_tx, recovery_id: int) -> int:
        """
        Convert Lotus recovery id into the transaction-specific v encoding.
        """

        if isinstance(unsigned_tx, TypedTransaction):
            return recovery_id  # EIP-2718: y_parity is raw 0 or 1
        elif isinstance(unsigned_tx, Transaction):
            return recovery_id + 35 + 2 * unsigned_tx.v  # EIP-155
        else:
            return recovery_id + 27

    def sign_transaction(self, tx_params: dict) -> SignedTransaction:
        sanitized = {k: v for k, v in tx_params.items() if k != "from"}
        unsigned_tx = serializable_unsigned_transaction_from_dict(sanitized)
        raw_bytes = LotusWalletTxSigner._unsigned_tx_to_raw_bytes(unsigned_tx)

        r, s, recovery_id = LotusWalletTxSigner._parse_rsv(Web3Service().wallet_sign(self.fil_address, raw_bytes, self.lotus_token))
        v = LotusWalletTxSigner.compute_v(unsigned_tx, recovery_id)

        encoded_tx = encode_transaction(unsigned_tx, vrs=(v, r, s))
        signed_tx = SignedTransaction(
            raw_transaction=HexBytes(encoded_tx),
            hash=HexBytes(keccak(encoded_tx)),
            r=r,
            s=s,
            v=v,
        )
        self._validate_recovered_transaction(signed_tx.raw_transaction)
        return signed_tx

    def sign_typed_data(self, domain_data: dict, message_types: dict, message_data: dict) -> SignedMessage:
        signable = encode_typed_data(domain_data, message_types, message_data)

        # pass the raw bytes so Lotus applies keccak256 to reach the correct EIP-712 hash
        raw_bytes = b"\x19" + signable.version + signable.header + signable.body

        sig = Web3Service().wallet_sign(self.fil_address, raw_bytes, self.lotus_token)
        r, s, recovery_id = LotusWalletTxSigner._parse_rsv(sig)
        v = recovery_id + 27

        signed_message = SignedMessage(
            message_hash=HexBytes(keccak(raw_bytes)),
            r=r,
            s=s,
            v=v,
            signature=HexBytes(sig[:64] + bytes([v])),
        )

        self._validate_recovered_typed_data(signable, signed_message.signature)
        return signed_message
