import base64
import hashlib
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import requests
from multiaddr import Multiaddr
from requests import RequestException, Response, Session

from cli.services.txsigner import TxSigner
from cli.services.web3_service import ActorId, Web3Service
from cli.services.web3_service import EthAddress, FilAddress


class CurioMarketDiscovery:
    @staticmethod
    def get_market_urls(provider_id: ActorId) -> list[str]:
        miner_info = Web3Service().state_miner_info(provider_id)
        raw_multiaddrs = miner_info.get("Multiaddrs") or []
        urls = []

        for raw_multiaddr_b64 in raw_multiaddrs:
            raw_multiaddr = base64.b64decode(raw_multiaddr_b64)
            multiaddr = Multiaddr(raw_multiaddr)

            url = CurioMarketDiscovery._multiaddr_to_http_url(multiaddr)

            if url is not None:
                urls.append(url)

        if not urls:
            raise RuntimeError(f"Storage Provider {provider_id} does not advertise a usable HTTP(S) market endpoint")

        return urls

    @staticmethod
    def _multiaddr_to_http_url(multiaddr: Multiaddr) -> str | None:
        protocols = {protocol.name for protocol in multiaddr.protocols()}
        host = None

        for protocol in ("dns", "dns4", "dns6", "ip4", "ip6"):
            # noinspection PyBroadException
            try:
                host = multiaddr.value_for_protocol(protocol)
                break

            # pylint: disable=broad-exception-caught
            except Exception:
                # nop
                pass

        if host is None:
            return None

        # noinspection PyBroadException
        try:
            # noinspection bad-argument-type
            port = int(multiaddr.value_for_protocol("tcp"))

        # pylint: disable=broad-exception-caught
        except Exception:
            return None

        if "https" in protocols or "wss" in protocols:
            scheme = "https"
        elif "http" in protocols or "ws" in protocols:
            scheme = "http"
        else:
            return None

        if ":" in str(host):
            host = f"[{host}]"

        default_port = (
                               scheme == "https" and port == 443
                       ) or (
                               scheme == "http" and port == 80
                       )

        if default_port:
            return f"{scheme}://{host}"

        return f"{scheme}://{host}:{port}"


class CurioMarketError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        self.status_code = status_code
        super().__init__(
            f"Curio Market request failed"
            f"{f' with HTTP {status_code}' if status_code is not None else ''}: "
            f"{message}"
        )


class CurioMarketClient:
    MARKET_PATH = "/market/mk20"
    REQUEST_TIMEOUT_SECONDS = 60

    def __init__(self,
                 base_url: str,
                 signer: TxSigner,
                 session: Session | None = None,
                 now: Callable[[], datetime] | None = None):
        #
        base_url = base_url.rstrip("/")

        if base_url.endswith(self.MARKET_PATH):
            self.base_url = base_url
        else:
            self.base_url = base_url + self.MARKET_PATH

        self.signer = signer
        self.session = session or requests.Session()
        self._now = now or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _delegated_filecoin_address_bytes(address: EthAddress) -> bytes:
        """
        Encode an EVM address as Filecoin delegated address bytes:
            protocol = 4 (delegated)
            namespace = 10 (Ethereum Address Manager)
            subaddress = 20-byte EVM address
        """

        eth_bytes = bytes.fromhex(str(address)[2:])

        if len(eth_bytes) != 20:
            raise ValueError(f"Expected 20-byte EVM address, got {len(eth_bytes)} bytes")

        return b"\x04\x0a" + eth_bytes

    def _auth_header(self, method: str, request_path: str) -> str:
        address_bytes = self._delegated_filecoin_address_bytes(self.signer.address())

        timestamp = (
            self._now()
            .astimezone(timezone.utc)
            .replace(second=0, microsecond=0)
            .strftime("%Y-%m-%dT%H:%M:00Z")
        )

        message = (
                address_bytes
                + method.upper().encode("utf-8")
                + request_path.encode("utf-8")
                + timestamp.encode("utf-8")
        )

        digest = hashlib.sha256(message).digest()

        # crypto.Signature.MarshalBinary():
        # 0x03 + 65-byte delegated signature
        signature = self.signer.sign_filecoin_message(digest)

        return (
            "CurioAuth delegated:"
            f"{base64.b64encode(address_bytes).decode('ascii')}:"
            f"{base64.b64encode(signature).decode('ascii')}"
        )

    def _request(self,
                 method: str,
                 path: str,
                 json_body: dict[str, Any] | None = None) -> Response:
        #
        if not path.startswith("/"):
            raise ValueError(f"Curio request path must start with '/': {path!r}")

        url = self.base_url + path
        request_path = urlsplit(url).path

        headers = {
            "Authorization": self._auth_header(method, request_path),
        }

        try:
            response = self.session.request(
                method=method,
                url=url,
                json=json_body,
                headers=headers,
                timeout=self.REQUEST_TIMEOUT_SECONDS,
            )

        except RequestException as e:
            raise CurioMarketError(str(e)) from e

        if response.status_code != 200:
            message = response.text.strip() or response.reason
            raise CurioMarketError(message, response.status_code)

        return response

    @staticmethod
    def _json(response: Response) -> dict[str, Any]:
        try:
            data = response.json()

        except ValueError as e:
            raise CurioMarketError(
                f"Invalid JSON response: {response.text!r}",
                response.status_code,
            ) from e

        if not isinstance(data, dict):
            raise CurioMarketError(
                f"Unexpected JSON response: {data!r}",
                response.status_code,
            )

        return data

    def get_products(self) -> list[str]:
        data = self._json(self._request("GET", "/products"))

        products = data.get("products")
        if not isinstance(products, list) or not all(isinstance(x, str) for x in products):
            raise CurioMarketError(f"Invalid products response: {data!r}")

        return products

    def get_sources(self) -> list[str]:
        data = self._json(self._request("GET", "/sources"))

        sources = data.get("sources")
        if not isinstance(sources, list) or not all(isinstance(x, str) for x in sources):
            raise CurioMarketError(f"Invalid sources response: {data!r}")

        return sources

    def get_contracts(self) -> list[str]:
        data = self._json(self._request("GET", "/contracts"))

        contracts = data.get("contracts")
        if not isinstance(contracts, list) or not all(isinstance(x, str) for x in contracts):
            raise CurioMarketError(f"Invalid contracts response: {data!r}")

        return contracts

    def get_deal_status(self, identifier: str) -> dict[str, Any]:
        return self._json(self._request("GET", f"/status/{identifier}"))

    def preflight(self, market_address: EthAddress):
        products = self.get_products()
        sources = self.get_sources()
        contracts = self.get_contracts()

        if "ddo_v1" not in products:
            raise CurioMarketError("SP does not support ddo_v1")

        if "retrieval_v1" not in products:
            raise CurioMarketError("SP does not support retrieval_v1")

        if "offline" not in sources:
            raise CurioMarketError("SP does not support offline data source")

        supported_contracts = {contract.lower() for contract in contracts}

        if str(market_address).lower() not in supported_contracts:
            raise CurioMarketError(f"Market contract {market_address} is not enabled by the SP")

    def submit_offline_ddo(self,
                           provider: ActorId | FilAddress,
                           piece_cid_v2: str,
                           duration_epochs: int,
                           market_address: EthAddress,
                           market_deal_id: int,
                           identifier: str,
                           notification_address: FilAddress | None = None,
                           notification_payload: bytes | None = None,
                           start_epoch: int | None = None,
                           indexing: bool = True,
                           announce_payload: bool = True):
        #
        if duration_epochs <= 0:
            raise ValueError("duration_epochs must be positive")

        if market_deal_id <= 0:
            raise ValueError("market_deal_id must be positive")

        if notification_address is None and notification_payload is not None:
            raise ValueError("notification_address is required when notification_payload is set")

        if notification_address is not None and notification_payload is None:
            raise ValueError("notification_payload is required when notification_address is set")

        ddo: dict[str, Any] = {
            "provider": str(provider),
            "duration": duration_epochs,
            "market_address": str(market_address),
            "market_deal_id": market_deal_id,
        }

        if start_epoch is not None:
            ddo["start_epoch"] = start_epoch

        if notification_address is not None:
            assert notification_payload is not None

            ddo["notification_address"] = str(notification_address)
            ddo["notification_payload"] = base64.b64encode(notification_payload).decode("ascii")

        deal = {
            "identifier": identifier,
            "client": str(self.signer.filecoin_address()),
            "data": {
                "piece_cid": {
                    "/": piece_cid_v2,
                },
                "format": {
                    "car": {},
                },
                "source_offline": {},
            },
            "products": {
                "ddo_v1": ddo,
                "retrieval_v1": {
                    "indexing": indexing,
                    "announce_payload": announce_payload,
                    "announce_piece": False,
                },
            },
        }

        self._request(
            "POST",
            "/deal",
            json_body=deal,
        )

    @staticmethod
    def deterministic_ulid(seed: bytes) -> str:
        alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

        entropy = int.from_bytes(
            hashlib.sha256(seed).digest()[:10],
            "big",
        )

        # timestamp = 0, entropy = deterministic 80 bits
        value = entropy
        result = []

        for _ in range(26):
            result.append(alphabet[value & 0x1F])
            value >>= 5

        return "".join(reversed(result))
