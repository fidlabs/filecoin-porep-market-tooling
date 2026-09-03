import json
import logging
from pathlib import Path
from typing import ClassVar, TypeVar

import click
import eth_abi
from eth_account.datastructures import SignedTransaction
from eth_typing import ABIElement
from hexbytes import HexBytes
# noinspection PyProtectedMember
from web3._utils.events import get_event_data
from web3.exceptions import ContractCustomError, Web3RPCError
from web3.types import EventData

from cli import utils
from cli._cli import is_dry_run
from cli.services.txsigner import TxSigner
from cli.services.web3_service import EthAddress, Web3Service, FilAddress

T = TypeVar("T")


@utils.json_dataclass()
class TxInfo:
    tx_hash: str
    transaction: object
    tx_receipt: dict
    events: list[EventData]


def _tx_to_log_string(operation, tx_params: dict | None) -> str:
    # operation.args is sensitive info, should never be logged
    # tx_params.data is sensitive info, should never be logged

    result = {
        "chainId": tx_params["chainId"],
        "from": tx_params["from"],
        "to": tx_params["to"],
        "signature": operation.signature,
        "nonce": tx_params["nonce"],
        "gas": tx_params["gas"],
        "value": tx_params["value"],
    } if tx_params else {
        "to": operation.address,
        "signature": operation.signature,
    }

    return utils.json_pretty(result)


class ContractService:
    _KNOWN_ABIS: ClassVar[list[ABIElement]] = []

    def __new__(cls, *args, **kwargs):
        return object.__new__(cls)

    def __init__(self, contract_address: EthAddress | FilAddress, contract_abi_path: Path):
        super().__init__()
        self.logger = logging.getLogger(self._get_class_name())
        self.web3 = Web3Service()

        with open(contract_abi_path, "r", encoding="utf-8") as abi_file:
            contract_abi = json.load(abi_file)
            self.contract = self.web3.contract(EthAddress.from_any(contract_address), contract_abi)

    def _get_class_name(self):
        return self.__class__.__name__

    @staticmethod
    def abi_dir() -> Path:
        return Path(__file__).parent / "contracts" / "abi"

    def address(self) -> EthAddress:
        return EthAddress(self.contract.address)

    def __decode_receipt_events(self, tx_receipt) -> list[EventData]:
        def find_event_in_abi(selector: bytes) -> ABIElement | None:
            for item in (i for i in ContractService.__get_known_abis() if i.get("type") == "event"):
                sig = item["name"] + "(" + ",".join(i["type"] for i in item["inputs"]) + ")"

                if self.web3.keccak(text=sig) == selector:
                    return item

            return None

        decoded_events = []

        for log in tx_receipt["logs"]:
            if not log["topics"]:
                continue

            abi_event = find_event_in_abi(bytes(log["topics"][0]))

            if abi_event is None:
                continue

            # noinspection PyBroadException
            try:
                # noinspection PyTypeChecker
                decoded_events.append(
                    get_event_data(
                        self.web3.w3().codec,
                        abi_event,
                        log,
                    ))

            # pylint: disable=broad-exception-caught
            except Exception:
                # nop
                # ruff: noqa: S112
                continue

        return decoded_events

    @staticmethod
    def __get_known_abis() -> list[ABIElement]:
        if ContractService._KNOWN_ABIS:
            return ContractService._KNOWN_ABIS

        ContractService._KNOWN_ABIS = []

        for abi_file in ContractService.abi_dir().glob("*.json"):
            with open(abi_file, "r", encoding="utf-8") as f:
                try:
                    ContractService._KNOWN_ABIS.extend(json.load(f))
                except json.JSONDecodeError:
                    continue

        return ContractService._KNOWN_ABIS

    def __decode_contract_error(self, err: ContractCustomError) -> str:
        # noinspection PyShadowingNames
        def find_error_in_abi(selector: bytes) -> ABIElement | None:
            for item in [i for i in ContractService.__get_known_abis() if i.get("type") == "error"]:
                sig = item["name"] + "(" + ",".join(i["type"] for i in item["inputs"]) + ")"

                if self.web3.keccak(text=sig)[:4] == selector:
                    return item

            return None

        # noinspection PyShadowingNames
        def format_error_args(abi_error: ABIElement, arg_data: bytes) -> str:
            types = [i["type"] for i in abi_error["inputs"]]
            names = [i["name"] for i in abi_error["inputs"]]
            decoded = eth_abi.decode(types, arg_data)

            return ", ".join(f"{n}={v}" for n, v in zip(names, decoded))

        if not err.data:
            return str(err)

        if isinstance(err.data, str):
            raw = bytes.fromhex(err.data.removeprefix("0x"))
        elif isinstance(err.data, (bytes, bytearray)):
            raw = bytes(err.data)
        else:
            return str(err)

        if len(raw) < 4:
            return str(err)

        hex_data = "0x" + raw.hex()
        selector, arg_data = raw[:4], raw[4:]
        abi_error = find_error_in_abi(selector)

        if not abi_error:
            return f"UnknownError hex={hex_data}"

        if not abi_error["inputs"]:
            return f"{abi_error['name']}"

        # noinspection PyBroadException
        try:
            return f"{abi_error['name']}({format_error_args(abi_error, arg_data)})"

        # pylint: disable=broad-exception-caught
        except Exception:
            return f"DecodingError name={abi_error['name']} hex={hex_data} err={str(err)}"

    def __send_tx(self, signed_tx: SignedTransaction, dry_run: bool) -> HexBytes:
        if dry_run or dry_run is None:  # should not happen
            raise RuntimeError("Attempted to send transaction in dry-run mode")

        return self.web3.send_raw_transaction(signed_tx)

    def _sign_and_send_tx(self, transaction, tx_params: dict, signer: TxSigner, dry_run: bool = False) -> TxInfo:
        # transaction.args is sensitive info, should never be logged
        # tx_params.data is sensitive info, should never be logged

        # signed_tx is sensitive info, should never be logged
        signed_tx = signer.sign_transaction(tx_params)

        if dry_run:
            # noinspection PyArgumentList
            return TxInfo(
                tx_hash=Web3Service.ZERO_TX_HASH,
                transaction=transaction,
                tx_receipt={},
                events=[]
            )

        # NOT DRY RUN, SENDING TRANSACTION

        tx_hash = self.__send_tx(signed_tx, dry_run)
        self.logger.warning(f"Transaction sent: {tx_hash.to_0x_hex()}: {_tx_to_log_string(transaction, tx_params)}")

        click.echo(f"Waiting for transaction {tx_hash.to_0x_hex()}...")
        tx_receipt = self.web3.wait_for_transaction_receipt(tx_hash, timeout=60 * 15, poll_latency=5)  # 15 minutes timeout, 5 seconds polling interval

        if tx_receipt["status"] == 0:
            # tx failed
            tx = self.web3.get_transaction(tx_hash)

            # this call should revert with the same error as the transaction
            reason = self.web3.call({"to": tx["to"], "from": tx["from"], "data": tx["input"]}, tx_receipt["blockNumber"])
            raise click.ClickException(f"Transaction reverted (reason unknown, call returned: {reason or 'empty'})")

        # tx succeeded
        self.logger.warning(f"Transaction succeeded: {tx_hash.to_0x_hex()}: {_tx_to_log_string(transaction, tx_params)}")

        # noinspection PyBroadException
        try:
            events = self.__decode_receipt_events(tx_receipt)

        # pylint: disable=broad-exception-caught
        except Exception as e:
            click.echo(f"Warning: Failed to decode events from transaction receipt: {e}")
            events = []

        # noinspection PyArgumentList
        return TxInfo(
            tx_hash=tx_hash.to_0x_hex(),
            transaction=transaction,
            tx_receipt=tx_receipt,
            events=events
        )

    def _handle_contract_error(self, err: Exception, operation, tx_params: dict | None):
        # tx_params.data is sensitive info, should never be logged

        if isinstance(err, ContractCustomError):
            reason = self.__decode_contract_error(err)
            self.logger.error(f"Contract operation reverted with error: {reason}: {_tx_to_log_string(operation, tx_params)}")
            raise click.ClickException(f"Contract operation reverted with error: {reason}: {_tx_to_log_string(operation, tx_params)}") from err

        elif isinstance(err, Web3RPCError):
            reason = err.rpc_response["error"]["message"] if (err.rpc_response and
                                                              "error" in err.rpc_response and
                                                              "message" in err.rpc_response["error"] and
                                                              err.rpc_response["error"]["message"]) else str(err)

            self.logger.error(f"Web3 RPC error: {reason}: {_tx_to_log_string(operation, tx_params)}")
            raise click.ClickException(f"Web3 RPC error: {reason}: {_tx_to_log_string(operation, tx_params)}") from err

        else:
            reason = str(err)
            self.logger.error(f"Contract operation failed: {reason}: {_tx_to_log_string(operation, tx_params)}")
            raise click.ClickException(f"Contract operation failed: {reason}: {_tx_to_log_string(operation, tx_params)}") from err

    def sign_and_send_tx(self, transaction, signer: TxSigner) -> TxInfo:
        # transaction.args is sensitive info, should never be logged

        from_address = signer.address()
        nonce = self.web3.get_address_nonce(from_address)
        tx_params = None

        # noinspection PyBroadException
        try:
            # tx_params.data is sensitive info, should never be logged
            tx_params = transaction.build_transaction({"from": from_address, "nonce": nonce})
            _dry_run = is_dry_run()

            if not utils.confirm(f"\n== DRY RUN: {_dry_run}\n"
                                 f"== Chain ID: {tx_params['chainId']} ({Web3Service().get_network_name(tx_params['chainId'])})\n"
                                 f"== Transaction:\n"
                                 f"==   from: {tx_params['from']}\n"
                                 f"==   to: {tx_params['to']}\n"
                                 f"==   signature: {transaction.signature}\n"
                                 f"==   nonce: {tx_params['nonce']}\n"
                                 f"==   gas price: {self.web3.get_gas_price()} wei\n"
                                 f"==   gas: {tx_params['gas']}\n"
                                 f"==   value: {tx_params['value']} wei\n"
                                 f"== This is the final confirmation", default=_dry_run):
                #
                click.echo("Enabling dry-run mode. This transaction WILL NOT be executed.")
                _dry_run = True

            click.echo()
            return self._sign_and_send_tx(transaction, tx_params, signer, _dry_run)

        # pylint: disable=broad-exception-caught
        except Exception as e:
            self._handle_contract_error(e, transaction, tx_params)
            assert False  # unreachable

    def call_contract(self, call) -> T:
        # noinspection PyBroadException
        try:
            return call.call()

        # pylint: disable=broad-exception-caught
        except Exception as e:
            self._handle_contract_error(e, call, None)
            assert False  # unreachable

    def call_contract_paginated(self, func, offset: int | None, limit: int | None, *args) -> T:
        if offset is not None and limit is not None:
            result, total = self.call_contract(func(*args, offset, limit))
            return result

        all_results = []
        offset = offset or 0
        limit = limit or 100

        while True:
            result, total = self.call_contract(func(*args, offset, limit))
            all_results.extend(result)

            if not result or len(all_results) >= total:
                return all_results

            offset += limit
