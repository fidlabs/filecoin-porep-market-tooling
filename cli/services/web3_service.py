import time
from typing import Dict

import click
from eth_account.datastructures import SignedTransaction
from eth_account.types import PrivateKeyType
from hexbytes import HexBytes
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import Web3RPCError
from web3.types import TxParams, BlockIdentifier, TxData, TxReceipt, RPCEndpoint

from cli import utils


# TODO LATER support testnet t0 id
class ActorId(int):
    VALID_PREFIXES = ("f0",)

    def __new__(cls, actor_id: int | str) -> "ActorId":
        if isinstance(actor_id, str):
            if actor_id.startswith(cls.VALID_PREFIXES):
                actor_id = actor_id[2:]
            try:
                actor_id = int(actor_id)
            except ValueError as e:
                raise ValueError(f"Invalid ActorId format: {actor_id!r}") from e

        if not isinstance(actor_id, int) or actor_id < 1000:
            raise ValueError(f"Invalid ActorId: {actor_id!r}")

        # noinspection PyTypeChecker
        return super().__new__(cls, actor_id)

    def __str__(self) -> str:
        return f"f0{int(self)}"

    def __repr__(self) -> str:
        return f"ActorId({int(self)})"

    @classmethod
    def try_parse(cls, actor_id: str | int) -> "ActorId | None":
        try:
            return cls(actor_id)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def is_actor_id(actor_id: str | int) -> bool:
        return ActorId.try_parse(actor_id) is not None

    def to_ethereum_address(self) -> "EthAddress":
        return EthAddress.from_filecoin_address(str(self))

    def to_filecoin_address(self) -> "FilAddress":
        response = Web3Service().w3().provider.make_request(
            RPCEndpoint("Filecoin.StateAccountKey"),
            [str(self), None]
        )

        if "error" in response:
            raise RuntimeError(response["error"])

        if not response.get("result"):
            raise RuntimeError(f"Failed to get Filecoin.StateAccountKey({self}): empty result")

        return FilAddress(response["result"])

    @staticmethod
    def from_any(xinput: str | int) -> "ActorId":
        if ActorId.is_actor_id(xinput):
            return ActorId(xinput)

        if isinstance(xinput, str):
            if FilAddress.is_filecoin_address(xinput):
                return FilAddress(xinput).to_actor_id()

            if EthAddress.is_ethereum_address(xinput):
                return EthAddress(xinput).to_actor_id()

        raise ValueError(f"Cannot convert {xinput!r} to ActorId: unsupported format")


class FilAddress(str):
    VALID_PREFIXES = ("f0", "f1", "f2", "f3", "f4",
                      "t0", "t1", "t2", "t3", "t4")

    def __new__(cls, addr: str) -> "FilAddress":
        if not isinstance(addr, str) or not addr.startswith(cls.VALID_PREFIXES) or len(addr) < 20:
            raise ValueError(f"Invalid Filecoin address format: {addr!r}")

        # noinspection PyTypeChecker
        return super().__new__(cls, addr)

    def __eq__(self, other):
        # noinspection PyBroadException
        try:
            other = FilAddress(other)

        # pylint: disable=broad-exception-caught
        except Exception:
            # nop
            pass

        return super().__eq__(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __bool__(self):
        return bool(str(self)) and not all(c == "0" for c in str(self)[2:])

    def __neg__(self):
        return not self.__bool__()

    def __hash__(self):
        return super().__hash__()

    @classmethod
    def try_parse(cls, addr: str) -> "FilAddress | None":
        try:
            return cls(addr)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def is_filecoin_address(addr: str) -> bool:
        return FilAddress.try_parse(addr) is not None

    def to_ethereum_address(self) -> "EthAddress":
        return EthAddress.from_filecoin_address(self)

    @staticmethod
    def from_ethereum_address(addr: str) -> "FilAddress":
        return EthAddress(addr).to_filecoin_address()

    def to_actor_id(self) -> ActorId:
        response = Web3Service().w3().provider.make_request(
            RPCEndpoint("Filecoin.StateLookupID"),
            [self, None]
        )

        if "error" in response:
            raise RuntimeError(response["error"])

        if not response.get("result"):
            raise RuntimeError(f"Failed to get Filecoin.StateLookupID({self}): empty result")

        return ActorId(response["result"])

    @staticmethod
    def from_any(xinput: str | int) -> "FilAddress":
        if ActorId.is_actor_id(xinput):
            return ActorId(xinput).to_filecoin_address()

        if isinstance(xinput, str):
            if FilAddress.is_filecoin_address(xinput):
                return FilAddress(xinput)

            if EthAddress.is_ethereum_address(xinput):
                return EthAddress(xinput).to_filecoin_address()

        raise ValueError(f"Cannot convert {xinput!r} to Filecoin address: unsupported format")


class EthAddress(str):
    ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

    def __new__(cls, addr: str) -> "EthAddress":
        # noinspection PyTypeChecker
        return super().__new__(cls, str(Web3.to_checksum_address(addr)))

    def __eq__(self, other):
        # noinspection PyBroadException
        try:
            other = EthAddress(other)

        # pylint: disable=broad-exception-caught
        except Exception:
            # nop
            pass

        return super().__eq__(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __bool__(self):
        return bool(str(self)) and self != EthAddress.ZERO_ADDRESS

    def __neg__(self):
        return not self.__bool__()

    def __hash__(self):
        return super().__hash__()

    @classmethod
    def try_parse(cls, addr: str) -> "EthAddress | None":
        try:
            return cls(addr)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def is_ethereum_address(addr: str) -> bool:
        return EthAddress.try_parse(addr) is not None

    def to_filecoin_address(self) -> FilAddress:
        return self.to_actor_id().to_filecoin_address()

    @staticmethod
    def from_filecoin_address(addr: str) -> "EthAddress":
        response = Web3Service().w3().provider.make_request(
            RPCEndpoint("Filecoin.FilecoinAddressToEthAddress"),
            [addr]
        )

        if "error" in response:
            raise RuntimeError(response["error"])

        if not response.get("result") or not Web3.is_address(response["result"]):
            raise ValueError(f"Failed to get Filecoin.FilecoinAddressToEthAddress({addr}): invalid result {response.get('result')!r}")

        return EthAddress(response["result"])

    def to_actor_id(self) -> ActorId:
        response = Web3Service().w3().provider.make_request(
            RPCEndpoint("Filecoin.EthAddressToFilecoinAddress"),
            [self]
        )

        if "error" in response:
            raise RuntimeError(response["error"])

        if not response.get("result"):
            raise ValueError(f"Failed to get Filecoin.EthAddressToFilecoinAddress({self}): empty result")

        if ActorId.is_actor_id(response["result"]):
            return ActorId(response["result"])
        elif FilAddress.is_filecoin_address(response["result"]):
            return FilAddress(response["result"]).to_actor_id()
        else:
            raise ValueError(f"Failed to get Filecoin.EthAddressToFilecoinAddress({self}): invalid result {response.get('result')!r}")

    @staticmethod
    def from_private_key(private_key: PrivateKeyType) -> "EthAddress":
        try:
            return EthAddress(Web3Service().w3().eth.account.from_key(private_key).address)
        except Exception as e:
            raise ValueError(f"Invalid private key: {str(e)}") from e

    @staticmethod
    def from_any(xinput: str | int) -> "EthAddress":
        if ActorId.is_actor_id(xinput):
            return ActorId(xinput).to_ethereum_address()

        if isinstance(xinput, str):
            if EthAddress.is_ethereum_address(xinput):
                return EthAddress(xinput)

            if FilAddress.is_filecoin_address(xinput):
                return FilAddress(xinput).to_ethereum_address()

        raise ValueError(f"Cannot convert {xinput!r} to Ethereum address: unsupported format")


class Web3Service:
    _instance: "Web3Service | None" = None
    ZERO_TX_HASH = "0x" + "00" * 32

    def __new__(cls) -> "Web3Service":
        if cls._instance is None:
            cls._instance = super().__new__(cls)

        assert cls._instance
        return cls._instance

    def __init__(self):
        if hasattr(self, "_w3"):
            return

        self._w3 = Web3(Web3.HTTPProvider(utils.get_env_required("RPC_URL")))

    def w3(self) -> Web3:
        return self._w3

    def get_chain_id(self) -> int:
        return self._w3.eth.chain_id

    def get_block_number(self) -> int:
        return self._w3.eth.block_number

    def keccak(self, text: str) -> bytes:
        return self._w3.keccak(text=text)

    def call(self, tx_params: TxParams, block_identifier: BlockIdentifier = "latest") -> str:
        return self._w3.eth.call(tx_params, block_identifier).to_0x_hex()

    def contract(self, address: EthAddress, abi: list[dict]) -> Contract:
        return self._w3.eth.contract(address=address, abi=abi)

    def get_transaction_count(self, from_address: EthAddress, block_identifier: BlockIdentifier = "pending") -> int:
        return self._w3.eth.get_transaction_count(from_address, block_identifier)

    def get_gas_price(self) -> int:
        return self._w3.eth.gas_price

    def get_transaction(self, tx_hash: HexBytes) -> TxData:
        return self._w3.eth.get_transaction(tx_hash)

    def send_raw_transaction(self, signed_tx: SignedTransaction) -> HexBytes:
        return self._w3.eth.send_raw_transaction(signed_tx.raw_transaction)

    def wait_for_transaction_receipt(self, tx_hash: HexBytes, timeout: int = 60 * 15, poll_latency: int = 5) -> TxReceipt:
        return self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout, poll_latency=poll_latency)

    def sign_transaction(self, tx_params: dict, from_private_key: PrivateKeyType) -> SignedTransaction:
        return self._w3.eth.account.sign_transaction(tx_params, from_private_key)

    def state_get_allocations(self, actor_id: ActorId) -> Dict[str, dict]:
        response = self._w3.provider.make_request(
            RPCEndpoint("Filecoin.StateGetAllocations"),
            [str(actor_id), None]
        )

        if "error" in response:
            raise RuntimeError(response["error"])

        if response.get("result") is None or not isinstance(response["result"], dict):
            raise RuntimeError(f"Failed to get Filecoin.StateGetAllocations({actor_id}): invalid result {response.get('result')!r}")

        return response["result"]

    def state_get_claims(self, actor_id: ActorId, client: ActorId | None = None) -> Dict[str, dict]:
        response = self._w3.provider.make_request(
            RPCEndpoint("Filecoin.StateGetClaims"),
            [str(actor_id), None]
        )

        if "error" in response:
            raise RuntimeError(response["error"])

        if response.get("result") is None or not isinstance(response["result"], dict):
            raise RuntimeError(f"Failed to get Filecoin.StateGetClaims({actor_id}): invalid result {response.get('result')!r}")

        if client is not None:
            return {claim_id: claim for claim_id, claim in response["result"].items() if claim.get("Client") == client}

        return response["result"]

    def wait_for_pending_transactions(self, from_address: EthAddress):
        _ = self.get_address_nonce(from_address, block_identifier="pending")

    def get_address_nonce(self, from_address: EthAddress, block_identifier: str = "pending") -> int:
        try:
            latest_nonce = self.get_transaction_count(from_address, "latest")
            if block_identifier == "latest":
                return latest_nonce

            assert block_identifier == "pending", f"Unsupported block identifier: {block_identifier}"
            pending_nonce = self.get_transaction_count(from_address, "pending")

            while pending_nonce > latest_nonce:
                # update pending_nonce loop
                click.echo(f"Address {from_address} has {pending_nonce - latest_nonce} pending transaction(s), waiting...")

                while pending_nonce > latest_nonce:
                    # update pending_nonce loop
                    latest_nonce = self.get_transaction_count(from_address, "latest")
                    time.sleep(5)

                pending_nonce = self.get_transaction_count(from_address, "pending")

            return pending_nonce

        except Web3RPCError as rpc_err:
            if "actor not found" in str(rpc_err).lower():
                return 0

            reason = rpc_err.rpc_response["error"]["message"] if (rpc_err.rpc_response and
                                                                  "error" in rpc_err.rpc_response and
                                                                  "message" in rpc_err.rpc_response["error"] and
                                                                  rpc_err.rpc_response["error"]["message"]) else str(rpc_err)

            raise RuntimeError(f"Web3 RPC error while getting nonce for address {from_address}: {reason}") from rpc_err

        except Exception as e:
            raise RuntimeError(f"Failed to get nonce for address {from_address}: {str(e)}") from e
