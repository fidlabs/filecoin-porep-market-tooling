import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

import cbor2

from cli.services.contracts.datacap_evidence_adapter import DataCapEvidenceAdapter, DataCapTransferParams
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.filecoinpay_validator import FileCoinPayRailStatus, FileCoinPayValidator
from cli.services.contracts.porep_market import PoRepMarket, PoRepMarketDealState, PoRepMarketDealType
from cli.services.contracts.legacy_porep_market import LegacyDeal, LegacyPoRepMarket, LegacyValidator
from cli.services.contracts.porep_market_view_helper import PoRepMarketDealView, PoRepMarketViewHelper
from cli.services.contracts.sector_status_inspector import SectorStatusInspector
from cli.services.web3_service import ActorId, EthAddress, Web3Service

EPOCHS_IN_DAY = 2_880
PREPARATION_BUFFER_EPOCHS = 30 * EPOCHS_IN_DAY
CLAIM_ROUNDING_RESERVE_EPOCHS = EPOCHS_IN_DAY
MAXIMUM_VERIFIED_ALLOCATION_TERM = 5 * 365 * EPOCHS_IN_DAY
DATACAP_PRECISION = 10 ** 18
VERIFIED_REGISTRY_ACTOR_ADDRESS = (b"\x00\x06",)
MAX_UINT64 = 2 ** 64 - 1
MAX_INT64 = 2 ** 63 - 1

_MARKER_RE = re.compile(
    r"^porep-migration=v1:(?P<chain>[1-9][0-9]*):(?P<market>0x[0-9a-fA-F]{40}):(?P<deal>[1-9][0-9]*)$"
)


class MigrationError(RuntimeError):
    pass


class MigrationProvenanceUnavailable(MigrationError):
    pass


def _sli_tuple(value) -> tuple[int, int, int, int]:
    if isinstance(value, Mapping):
        return (
            int(value["retrievabilityBps"]),
            int(value["bandwidthBytesPerSecond"]),
            int(value["latencyMs"]),
            int(value["indexingPct"]),
        )
    return tuple(int(item) for item in value)


def _slis_meet(promised: tuple[int, int, int, int], requested: tuple[int, int, int, int]) -> bool:
    return (
        (requested[0] == 0 or promised[0] >= requested[0])
        and (requested[1] == 0 or promised[1] >= requested[1])
        and (requested[2] == 0 or (promised[2] != 0 and promised[2] <= requested[2]))
        and (requested[3] == 0 or promised[3] >= requested[3])
    )


@dataclass(frozen=True)
class MigrationMarker:
    source_chain_id: int
    source_market: EthAddress
    source_deal_id: int

    def fragment(self) -> str:
        return f"porep-migration=v1:{self.source_chain_id}:{self.source_market}:{self.source_deal_id}"


@dataclass(frozen=True)
class Claim:
    claim_id: int
    provider: ActorId
    client: ActorId
    data: str
    size: int
    term_min: int
    term_max: int
    term_start: int
    sector: int

    @property
    def end_epoch(self) -> int:
        return self.term_start + self.term_max

    @classmethod
    def from_rpc(cls, claim_id: int, data: dict) -> "Claim":
        def value(*names):
            for name in names:
                if name in data:
                    return data[name]
            raise MigrationError(f"Claim {claim_id} is missing {names[0]}")

        return cls(
            claim_id=claim_id,
            provider=ActorId(value("Provider", "provider")),
            client=ActorId(value("Client", "client")),
            data=str(value("Data", "data")),
            size=int(value("Size", "size")),
            term_min=int(value("TermMin", "term_min")),
            term_max=int(value("TermMax", "term_max")),
            term_start=int(value("TermStart", "term_start")),
            sector=int(value("Sector", "sector")),
        )


@dataclass(frozen=True)
class ClaimExtension:
    provider: ActorId
    claim_id: int
    new_term_max: int
    size: int


@dataclass(frozen=True)
class AdoptionPlan:
    source_claims: tuple[Claim, ...]
    target_ids: frozenset[int]
    extensions: tuple[ClaimExtension, ...]
    operator_data: bytes
    datacap_amount: int
    sector_target_epoch: int

    @property
    def complete(self) -> bool:
        return not self.extensions and self.target_ids == frozenset(claim.claim_id for claim in self.source_claims)

    def batches(self, size: int = 100) -> list["AdoptionPlan"]:
        if size <= 0:
            raise ValueError("Adoption batch size must be positive")
        result = []
        for offset in range(0, len(self.extensions), size):
            extensions = self.extensions[offset:offset + size]
            result.append(AdoptionPlan(
                source_claims=self.source_claims,
                target_ids=self.target_ids,
                extensions=extensions,
                operator_data=claim_extension_cbor(extensions),
                datacap_amount=sum(extension.size for extension in extensions) * DATACAP_PRECISION,
                sector_target_epoch=self.sector_target_epoch,
            ))
        return result


@dataclass(frozen=True)
class MigrationPair:
    marker: MigrationMarker
    source: LegacyDeal
    target: PoRepMarketDealView


def parse_migration_marker(location: str) -> MigrationMarker | None:
    fragment = urlsplit(location).fragment
    if not fragment:
        return None
    match = _MARKER_RE.fullmatch(fragment)
    if not match:
        raise MigrationError(f"Conflicting or malformed manifest fragment: #{fragment}")
    chain_id = int(match.group("chain"))
    deal_id = int(match.group("deal"))
    if chain_id > MAX_UINT64 or deal_id > 2 ** 256 - 1:
        raise MigrationError("Migration marker contains an out-of-range chain or deal ID")
    return MigrationMarker(chain_id, EthAddress(match.group("market")), deal_id)


def migration_manifest_location(original: str, marker: MigrationMarker) -> str:
    if "#" in original:
        raise MigrationError(f"Source manifest already has a fragment separator: {original}")
    return f"{original}#{marker.fragment()}"


def claim_extension_cbor(extensions: list[ClaimExtension] | tuple[ClaimExtension, ...]) -> bytes:
    rows = []
    for extension in extensions:
        values = (int(extension.provider), extension.claim_id, extension.new_term_max)
        if any(value < 0 or value > MAX_UINT64 for value in values):
            raise MigrationError("Claim extension contains a value outside the CBOR uint64 range")
        rows.append(list(values))
    return cbor2.dumps([[], rows], canonical=True)


def build_adoption_plan(source_claims: list[Claim],
                        target_pending_ids: list[int],
                        target_confirmed_ids: list[int],
                        target_epoch: int,
                        current_epoch: int) -> AdoptionPlan:
    source_ids = [claim.claim_id for claim in source_claims]
    if not source_ids or len(set(source_ids)) != len(source_ids):
        raise MigrationError("Source claim IDs are empty or duplicated")
    pending = [int(value) for value in target_pending_ids]
    confirmed = [int(value) for value in target_confirmed_ids]
    if len(set(pending)) != len(pending) or len(set(confirmed)) != len(confirmed):
        raise MigrationError("Target adapter contains duplicate claim IDs")
    overlap = set(pending) & set(confirmed)
    if overlap:
        raise MigrationError(f"Target adapter repeats IDs in pending and confirmed sets: {sorted(overlap)}")
    target_ids = frozenset(pending + confirmed)
    foreign = target_ids - set(source_ids)
    if foreign:
        raise MigrationError(f"Target adapter contains foreign claim IDs: {sorted(foreign)}")
    if target_epoch <= current_epoch:
        raise MigrationError(
            f"Migration preparation target {target_epoch} is no longer in the future at epoch {current_epoch}"
        )

    extensions = []
    for claim in source_claims:
        if claim.end_epoch <= current_epoch:
            raise MigrationError(f"Source claim {claim.claim_id} expired at epoch {claim.end_epoch}")
        if claim.claim_id in target_ids:
            if claim.end_epoch <= target_epoch:
                raise MigrationError(
                    f"Claim {claim.claim_id} is already registered but ends at {claim.end_epoch}, before sector target {target_epoch}"
                )
            continue
        new_term_max = max(
            claim.term_max + 1,
            target_epoch + CLAIM_ROUNDING_RESERVE_EPOCHS - claim.term_start + 1,
        )
        actor_limit = current_epoch + MAXIMUM_VERIFIED_ALLOCATION_TERM - claim.term_start
        if new_term_max > actor_limit or new_term_max > MAX_INT64:
            raise MigrationError(
                f"Claim {claim.claim_id} needs term max {new_term_max}, above the current actor limit {actor_limit}"
            )
        extensions.append(ClaimExtension(claim.provider, claim.claim_id, new_term_max, claim.size))

    encoded = claim_extension_cbor(extensions)
    return AdoptionPlan(
        source_claims=tuple(source_claims),
        target_ids=target_ids,
        extensions=tuple(extensions),
        operator_data=encoded,
        datacap_amount=sum(extension.size for extension in extensions) * DATACAP_PRECISION,
        sector_target_epoch=target_epoch,
    )


def duplicate_id_assignments(assignments: dict[int, list[int]]) -> dict[int, list[int]]:
    owners: dict[int, list[int]] = {}
    for deal_id, ids in assignments.items():
        for claim_id in set(ids):
            owners.setdefault(claim_id, []).append(deal_id)
    return {claim_id: deal_ids for claim_id, deal_ids in owners.items() if len(deal_ids) > 1}


class MigrationService:
    def __init__(self,
                 trusted_source_market: EthAddress,
                 source_chain_id: int | None = None,
                 web3: Web3Service | None = None,
                 view_helper: PoRepMarketViewHelper | None = None):
        self.web3 = web3 or Web3Service()
        self.source_chain_id = source_chain_id or self.web3.get_chain_id()
        self.trusted_source_market = EthAddress(trusted_source_market)
        self.source_market = LegacyPoRepMarket(self.trusted_source_market)
        self.view_helper = view_helper or PoRepMarketViewHelper()
        self.discovery_errors: list[str] = []

    def discover(self,
                 client: EthAddress | None = None,
                 provider: ActorId | None = None,
                 deal_id: int | None = None,
                 limit: int | None = None) -> list[MigrationPair]:
        views = self.view_helper.get_deal_views()
        self.discovery_errors = []
        scoped_views = [
            view for view in views
            if (client is None or view.deal.client_address == client)
            and (provider is None or view.deal.provider_id == provider)
            and (deal_id is None or view.deal.deal_id == deal_id)
        ]
        parsed_markers: dict[int, MigrationMarker] = {}
        for view in views:
            try:
                marker = parse_migration_marker(view.data.manifest_location)
            except MigrationError as exc:
                if view in scoped_views:
                    self.discovery_errors.append(f"V2 {view.deal.deal_id}: {exc}")
                continue
            if marker is None:
                continue
            try:
                self._validate_trusted_marker(marker)
            except MigrationError as exc:
                if view in scoped_views:
                    self.discovery_errors.append(f"V2 {view.deal.deal_id}: {exc}")
                continue
            parsed_markers[view.deal.deal_id] = marker
        relevant_sources = {
            parsed_markers[view.deal.deal_id].source_deal_id
            for view in scoped_views
            if view.deal.deal_id in parsed_markers
        }
        authoritative: dict[int, MigrationPair] = {}
        for view in views:
            marker = parsed_markers.get(view.deal.deal_id)
            if marker is None or marker.source_deal_id not in relevant_sources:
                continue
            try:
                authoritative[view.deal.deal_id] = self._authoritative_pair(view, marker)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                if view in scoped_views:
                    self.discovery_errors.append(f"V2 {view.deal.deal_id}: {exc}")
        source_targets: dict[int, list[int]] = {}
        for target_id, pair in authoritative.items():
            source_targets.setdefault(pair.marker.source_deal_id, []).append(target_id)
        duplicate_sources = {source for source, targets in source_targets.items() if len(targets) > 1}
        pairs = []
        for view in scoped_views:
            pair = authoritative.get(view.deal.deal_id)
            if pair is None:
                continue
            if pair.marker.source_deal_id in duplicate_sources:
                self.discovery_errors.append(
                    f"V2 {view.deal.deal_id}: V1 {pair.marker.source_deal_id} has ambiguous V2 references "
                    f"{source_targets[pair.marker.source_deal_id]}"
                )
                continue
            pairs.append(pair)
        pairs.sort(key=lambda pair: pair.target.deal.deal_id)
        return pairs[:limit] if limit is not None else pairs

    def source_reference_targets(self, source_deal_id: int) -> list[int]:
        targets = []
        for view in self.view_helper.get_deal_views():
            try:
                marker = parse_migration_marker(view.data.manifest_location)
                if marker is not None:
                    self._validate_trusted_marker(marker)
                    if marker.source_deal_id == source_deal_id:
                        try:
                            source = self.source_market.get_deal(source_deal_id)
                        except Exception as exc:
                            raise MigrationProvenanceUnavailable(
                                f"Cannot determine whether V2 {view.deal.deal_id} already references V1 "
                                f"{source_deal_id}: {exc}"
                            ) from exc
                        pair = MigrationPair(marker, source, view)
                        try:
                            self.validate_pair(pair)
                            self._validate_migration_policy(pair)
                            self.verify_direct_creation(pair)
                        except MigrationProvenanceUnavailable:
                            raise
                        except MigrationError:
                            continue
                        except Exception as exc:
                            raise MigrationProvenanceUnavailable(
                                f"Cannot verify existing V2 {view.deal.deal_id}: {exc}"
                            ) from exc
                        targets.append(view.deal.deal_id)
            except MigrationProvenanceUnavailable:
                raise
            except Exception:  # noqa: S112  # pylint: disable=broad-exception-caught
                continue
        return sorted(targets)

    def _authoritative_pair(self, view: PoRepMarketDealView, marker: MigrationMarker) -> MigrationPair:
        source = self.source_market.get_deal(marker.source_deal_id)
        pair = MigrationPair(marker, source, view)
        self.validate_pair(pair)
        self._validate_migration_policy(pair)
        self.verify_direct_creation(pair)
        return pair

    def _validate_migration_policy(self, pair: MigrationPair):
        target = pair.target
        if target.terms.duration_epochs != 180 * EPOCHS_IN_DAY:
            raise MigrationError("Authoritative migration deals must have an exact 180-day duration")
        if target.deal.deal_type != PoRepMarketDealType.PUBLIC:
            raise MigrationError("Authoritative migration deals must use the PUBLIC deal type")
        adapter = DataCapEvidenceAdapter(target.deal.evidence_adapter_address)
        if adapter.evidence_type().value != 10:
            raise MigrationError("Authoritative migration deal does not use DataCap evidence type 10")
        if adapter.get_porep_market_contract_address() != self.view_helper.porep_market_contract():
            raise MigrationError("Authoritative migration adapter belongs to a different V2 PoRep Market")

    def _validate_trusted_marker(self, marker: MigrationMarker):
        if marker.source_chain_id != self.source_chain_id:
            raise MigrationError(
                f"Migration marker chain {marker.source_chain_id} does not match connected chain {self.source_chain_id}"
            )
        if marker.source_market != self.trusted_source_market:
            raise MigrationError(
                f"Migration marker market {marker.source_market} does not match trusted V1 market {self.trusted_source_market}"
            )

    @staticmethod
    def validate_pair(pair: MigrationPair):
        source = pair.source
        target = pair.target
        if source.client != target.deal.client_address:
            raise MigrationError(f"V2 deal {target.deal.deal_id} client does not match V1 deal {source.deal_id}")
        if source.provider != target.deal.provider_id:
            raise MigrationError(f"V2 deal {target.deal.deal_id} provider does not match V1 deal {source.deal_id}")
        if source.size_bytes != target.terms.requested_size_bytes:
            raise MigrationError(f"V2 deal {target.deal.deal_id} size does not match V1 deal {source.deal_id}")
        expected_location = migration_manifest_location(source.manifest_location, pair.marker)
        if target.data.manifest_location != expected_location:
            raise MigrationError(f"V2 deal {target.deal.deal_id} manifest location is not the canonical V1 migration location")
        if bytes(target.data.manifest_hash) != source.manifest_hash:
            raise MigrationError(f"V2 deal {target.deal.deal_id} manifest hash does not match V1 deal {source.deal_id}")

    def verify_direct_creation(self, pair: MigrationPair):
        """Bind mutable deal data to its successful direct admin proposal transaction."""
        market_address = self.view_helper.porep_market_contract()
        market = PoRepMarket(market_address)
        event = market.contract.events.DealCreated()
        try:
            logs = event.get_logs(
                from_block=pair.target.deal.proposed_at_epoch,
                to_block=pair.target.deal.proposed_at_epoch,
                argument_filters={"dealId": pair.target.deal.deal_id},
            )
        except Exception as exc:
            raise MigrationProvenanceUnavailable(
                f"Cannot verify direct proposal provenance for V2 deal {pair.target.deal.deal_id}: {exc}"
            ) from exc
        if len(logs) != 1:
            raise MigrationError(
                f"Expected one creation log for V2 deal {pair.target.deal.deal_id}, found {len(logs)}"
            )
        log = logs[0]
        args = log["args"]
        expected = pair.target
        event_slis = _sli_tuple(args["requirements"])
        expected_slis = (
            expected.required_slis.retrievability_bps,
            expected.required_slis.bandwidth_bytes_per_second,
            expected.required_slis.latency_ms,
            expected.required_slis.indexing_pct,
        )
        if (EthAddress(args["client"]) != expected.deal.client_address
                or ActorId(args["provider"]) != expected.deal.provider_id
                or bytes(args["manifestHash"]) != bytes(expected.data.manifest_hash)
                or str(args["manifestLocation"]) != expected.data.manifest_location
                or int(args["totalDealSize"]) != expected.terms.requested_size_bytes
                or int(args["proposedAtBlock"]) != expected.deal.proposed_at_epoch):
            raise MigrationError(f"V2 deal {expected.deal.deal_id} mutable data differs from its creation event")
        try:
            tx = self.web3.get_transaction(log["transactionHash"])
            receipt = self.web3.w3().eth.get_transaction_receipt(log["transactionHash"])
        except Exception as exc:
            raise MigrationProvenanceUnavailable(
                f"Cannot read proposal transaction for V2 deal {expected.deal.deal_id}: {exc}"
            ) from exc
        if int(receipt["status"]) != 1 or EthAddress(tx["to"]) != market_address:
            raise MigrationError(f"V2 deal {expected.deal.deal_id} was not created by a successful direct market call")
        try:
            function, params = market.contract.decode_function_input(tx["input"])
        except Exception as exc:
            raise MigrationProvenanceUnavailable(
                f"Unsupported proposal provenance for V2 deal {expected.deal.deal_id}; direct calldata cannot be decoded"
            ) from exc
        if function.fn_name != "proposeDealWithSpecificOffer":
            raise MigrationError(
                f"V2 deal {expected.deal.deal_id} was not created by direct proposeDealWithSpecificOffer"
            )
        request = params["request"]
        request_location = request.get("manifestLocation") if isinstance(request, Mapping) else request[3]
        request_hash = request.get("manifestHash") if isinstance(request, Mapping) else request[0]
        request_size = request.get("requestedSizeBytes") if isinstance(request, Mapping) else request[1]
        request_price = request.get("maxPricePer32GiBPerMonth") if isinstance(request, Mapping) else request[2]
        request_token = request.get("paymentToken") if isinstance(request, Mapping) else request[4]
        request_days = request.get("durationDays") if isinstance(request, Mapping) else request[5]
        request_type = request.get("dealType") if isinstance(request, Mapping) else request[6]
        request_slis = request.get("requiredSLIs") if isinstance(request, Mapping) else request[7]
        request_slis = _sli_tuple(request_slis)
        if (int(params["offerId"]) != expected.deal.offer_id
                or EthAddress(params["client"]) != expected.deal.client_address
                or str(request_location) != expected.data.manifest_location
                or bytes(request_hash) != bytes(expected.data.manifest_hash)
                or int(request_size) != expected.terms.requested_size_bytes
                or expected.payment.price_per_32_gib_per_month <= 0
                or expected.payment.price_per_32_gib_per_month > int(request_price)
                or EthAddress(request_token) != expected.payment.payment_token
                or int(request_days) != 180
                or int(request_type) != expected.deal.deal_type.value
                or event_slis != request_slis
                or not _slis_meet(expected_slis, request_slis)):
            raise MigrationError(f"V2 deal {expected.deal.deal_id} does not match its proposal calldata")

    def source_claims(self, pair: MigrationPair, tipset_key: list[dict] | None = None) -> list[Claim]:
        return self._source_claims(pair.source, tipset_key)

    def _source_claims(self, source: LegacyDeal, tipset_key: list[dict] | None = None) -> list[Claim]:
        tipset_key = tipset_key or self.web3.get_tipset_key()
        legacy_client = self.source_market.get_client_contract()
        ids = legacy_client.allocation_ids(source.deal_id)
        if not ids or len(ids) != len(set(ids)):
            raise MigrationError(f"V1 deal {source.deal_id} has no claims or duplicate claim IDs")
        if legacy_client.allocated_size(source.deal_id) != source.size_bytes:
            raise MigrationError(f"V1 deal {source.deal_id} does not have exact full claimed size")
        expected_client = legacy_client.address().to_actor_id()
        rpc_claims = self.web3.state_get_claims(source.provider, tipset_key=tipset_key)
        claims = []
        for claim_id in ids:
            raw = rpc_claims.get(str(claim_id))
            if raw is None:
                raise MigrationError(f"V1 claim {claim_id} is missing from provider {source.provider}")
            claim = Claim.from_rpc(claim_id, raw)
            if legacy_client.is_claim_terminated(claim_id):
                raise MigrationError(f"V1 claim {claim_id} is marked terminated")
            if claim.client != expected_client:
                raise MigrationError(f"V1 claim {claim_id} belongs to client actor {claim.client}, expected {expected_client}")
            if claim.provider != source.provider:
                raise MigrationError(f"V1 claim {claim_id} belongs to provider {claim.provider}")
            if not claim.data or claim.size <= 0 or claim.sector < 0:
                raise MigrationError(f"V1 claim {claim_id} has invalid piece, size, or sector data")
            claims.append(claim)
        if sum(claim.size for claim in claims) != source.size_bytes:
            raise MigrationError(f"V1 deal {source.deal_id} claim bytes do not equal the full deal size")
        return claims

    def source_inventory(self, source_deal_id: int) -> tuple[LegacyDeal, list[Claim]]:
        source = self.source_market.get_deal(source_deal_id)
        tipset_key = self.web3.get_tipset_key()
        claims = self._source_claims(source, tipset_key)
        self._qualify_source_rail(source)
        try:
            active = self.web3.state_miner_active_sectors(source.provider, tipset_key)
        except Exception as exc:
            raise MigrationError(str(exc)) from exc
        active_numbers = {
            int(row.get("SectorNumber", row.get("sector_number", -1)))
            for row in active
        }
        missing = sorted({claim.sector for claim in claims} - active_numbers)
        if missing:
            raise MigrationError(f"V1 deal {source_deal_id} has claims in non-active sectors: {missing}")
        return source, claims

    def _qualify_source_rail(self, source: LegacyDeal):
        current_epoch = self.web3.get_block_number()
        if source.state != LegacyDeal.COMPLETED:
            raise MigrationError(f"V1 deal {source.deal_id} is not Completed")
        if not source.rail_id:
            raise MigrationError(f"V1 deal {source.deal_id} has no payment rail")
        try:
            rail = FileCoinPay().get_rail(source.rail_id)
        except Exception as exc:
            raise MigrationError(f"V1 deal {source.deal_id} rail is unavailable: {exc}") from exc
        if rail.payment_rate <= 0 or rail.end_epoch != 0:
            raise MigrationError(f"V1 deal {source.deal_id} rail is stopped or has a non-positive rate")
        if (rail.from_address != source.client
                or rail.operator != source.validator
                or rail.validator != source.validator):
            raise MigrationError(f"V1 deal {source.deal_id} rail identity does not match its client and validator")
        if not rail.token or not rail.to_address:
            raise MigrationError(f"V1 deal {source.deal_id} rail has an invalid token or payee")
        end_epoch = LegacyValidator(source.validator).deal_end_epoch(
            source.deal_id, source.proposed_at_epoch, current_epoch
        )
        if end_epoch <= current_epoch:
            raise MigrationError(f"V1 deal {source.deal_id} service expired at epoch {end_epoch}")

    def qualify_running_source(self,
                               pair: MigrationPair,
                               claims: list[Claim],
                               tipset_key: list[dict] | None = None):
        tipset_key = tipset_key or self.web3.get_tipset_key()
        current_epoch = self.web3.get_block_number()
        self._qualify_source_rail(pair.source)

        inspector = SectorStatusInspector()
        if inspector.porep_market_contract() != self.view_helper.porep_market_contract():
            raise MigrationError("Sector status inspector belongs to a different V2 PoRep Market")
        for claim in claims:
            partition = self.web3.state_sector_partition(pair.source.provider, claim.sector, tipset_key)
            deadline = int(partition.get("Deadline", partition.get("deadline", -1)))
            partition_index = int(partition.get("Partition", partition.get("partition", -1)))
            info = self.web3.state_sector_get_info(pair.source.provider, claim.sector, tipset_key)
            if info is None:
                raise MigrationError(f"Sector {claim.sector} for V1 claim {claim.claim_id} is missing")
            expiration = int(info.get("Expiration", info.get("expiration", 0)))
            if expiration <= current_epoch:
                raise MigrationError(f"Sector {claim.sector} for V1 claim {claim.claim_id} is expired")
            if not inspector.is_active(pair.target.deal.deal_id, claim.sector, deadline, partition_index):
                raise MigrationError(f"Sector {claim.sector} for V1 claim {claim.claim_id} is not active")

    def adoption_plan(self, pair: MigrationPair) -> AdoptionPlan:
        adapter = DataCapEvidenceAdapter(pair.target.deal.evidence_adapter_address)
        if adapter.get_porep_market_contract_address() != self.view_helper.porep_market_contract():
            raise MigrationError("V2 evidence adapter belongs to a different PoRep Market")
        if adapter.evidence_type().value != 10:
            raise MigrationError("V2 deal does not use the VerifReg claims evidence adapter")
        pending = self._all_adapter_ids(adapter.get_allocation_ids_per_deal, pair.target.deal.deal_id)
        confirmed = self._all_adapter_ids(adapter.get_claim_ids, pair.target.deal.deal_id)
        target_epoch = (
            pair.target.deal.proposed_at_epoch
            + pair.target.terms.duration_epochs
            + PREPARATION_BUFFER_EPOCHS
        )
        tipset_key = self.web3.get_tipset_key()
        claims = self.source_claims(pair, tipset_key)
        self._reject_cross_deal_ids(
            {claim.claim_id for claim in claims}, pair.target.deal.deal_id
        )
        self.qualify_running_source(pair, claims, tipset_key)
        current_epoch = self.web3.get_block_number()
        latest_preparation_epoch = pair.target.deal.proposed_at_epoch + PREPARATION_BUFFER_EPOCHS
        if current_epoch > latest_preparation_epoch:
            raise MigrationError(
                f"V2 deal {pair.target.deal.deal_id} passed its fixed preparation deadline "
                f"{latest_preparation_epoch} at epoch {current_epoch}"
            )
        plan = build_adoption_plan(claims, pending, confirmed, target_epoch, current_epoch)
        claims_by_id = {claim.claim_id: claim for claim in claims}
        expected_registered_bytes = sum(claims_by_id[claim_id].size for claim_id in plan.target_ids)
        actual_registered_bytes = adapter.get_allocated_bytes(pair.target.deal.deal_id)
        if actual_registered_bytes != expected_registered_bytes:
            raise MigrationError(
                f"V2 adapter records {actual_registered_bytes} bytes for registered source claims; "
                f"expected {expected_registered_bytes}"
            )
        return plan

    def _reject_cross_deal_ids(self, source_ids: set[int], target_deal_id: int):
        owners: dict[int, list[int]] = {}
        adapters = {}
        for view in self.view_helper.get_deal_views():
            address = view.deal.evidence_adapter_address
            if address not in adapters:
                adapters[address] = DataCapEvidenceAdapter(address)
            adapter = adapters[address]
            try:
                evidence_type = adapter.evidence_type().value
            except Exception as exc:
                raise MigrationError(f"Cannot classify V2 evidence adapter {address}: {exc}") from exc
            if evidence_type != 10:
                continue
            try:
                bound_market = adapter.get_porep_market_contract_address()
            except Exception as exc:
                raise MigrationError(f"Cannot verify DataCap adapter {address} market binding: {exc}") from exc
            if bound_market != self.view_helper.porep_market_contract():
                continue
            pending = self._all_adapter_ids(adapter.get_allocation_ids_per_deal, view.deal.deal_id)
            confirmed = self._all_adapter_ids(adapter.get_claim_ids, view.deal.deal_id)
            for claim_id in set(pending + confirmed):
                owners.setdefault(claim_id, []).append(view.deal.deal_id)
        conflicts = {
            claim_id: deal_ids
            for claim_id, deal_ids in owners.items()
            if claim_id in source_ids
            and (len(deal_ids) > 1 or deal_ids[0] != target_deal_id)
        }
        if conflicts:
            raise MigrationError(f"Source claim IDs are assigned to other V2 deals: {conflicts}")

    @staticmethod
    def _all_adapter_ids(get_page, deal_id: int) -> list[int]:
        ids = []
        offset = 0
        while True:
            page, total = get_page(deal_id, offset, 100)
            ids.extend(int(value) for value in page)
            if not page or len(ids) >= int(total):
                return ids
            offset += len(page)

    @staticmethod
    def transfer_params(plan: AdoptionPlan) -> DataCapTransferParams:
        amount = plan.datacap_amount.to_bytes((plan.datacap_amount.bit_length() + 7) // 8, "big")
        return DataCapTransferParams(
            to=VERIFIED_REGISTRY_ACTOR_ADDRESS,
            amount=(amount, False),
            operator_data=plan.operator_data,
        )

    def validate_active_replacement(self, pair: MigrationPair) -> MigrationPair:
        target = self.view_helper.get_deal_view(pair.target.deal.deal_id)
        pair = MigrationPair(pair.marker, pair.source, target)
        self.validate_pair(pair)
        self._validate_migration_policy(pair)
        if target.deal.state != PoRepMarketDealState.ACTIVE:
            raise MigrationError(f"V2 deal state is {target.deal.state}, expected ACTIVE")
        if target.capacity.committed_bytes != pair.source.size_bytes:
            raise MigrationError("V2 committed bytes do not equal the full V1 deal size")
        if (target.service.service_start_epoch <= 0
                or target.service.service_end_epoch - target.service.service_start_epoch
                != target.terms.duration_epochs):
            raise MigrationError("V2 service window does not match its frozen duration")
        if not target.deal.rail_id or target.payment.rail_max_rate_per_epoch <= 0:
            raise MigrationError("V2 deal has no active payment rate or rail")
        pay = FileCoinPay()
        rail = pay.get_rail(target.deal.rail_id)
        if (rail.from_address != target.deal.client_address
                or rail.to_address != target.payment.payee
                or rail.token != target.payment.payment_token
                or rail.operator != target.deal.validator_address
                or rail.validator != target.deal.validator_address
                or rail.payment_rate != target.payment.rail_max_rate_per_epoch
                or rail.end_epoch != 0):
            raise MigrationError("V2 active rail does not match its frozen actors, token, rate, and open state")
        if FileCoinPayValidator(target.deal.validator_address).get_rail_status() != FileCoinPayRailStatus.ACTIVE:
            raise MigrationError("V2 validator rail is not ACTIVE")
        current_epoch = self.web3.get_block_number()
        account = pay.get_account_info_if_settled(target.payment.payment_token, target.deal.client_address)
        if account.funded_until_epoch <= current_epoch:
            raise MigrationError(
                f"V2 payer account is funded only through epoch {account.funded_until_epoch}"
            )
        adapter = DataCapEvidenceAdapter(target.deal.evidence_adapter_address)
        pending = self._all_adapter_ids(adapter.get_allocation_ids_per_deal, target.deal.deal_id)
        confirmed = self._all_adapter_ids(adapter.get_claim_ids, target.deal.deal_id)
        tipset_key = self.web3.get_tipset_key()
        claims = self.source_claims(pair, tipset_key)
        expected_ids = {claim.claim_id for claim in claims}
        if pending or set(confirmed) != expected_ids or len(confirmed) != len(expected_ids):
            raise MigrationError("V2 requires an empty pending set and the exact confirmed V1 claim set")
        if adapter.get_allocated_bytes(target.deal.deal_id) != pair.source.size_bytes:
            raise MigrationError("V2 adapter bytes do not equal the full V1 deal size")
        if not adapter.is_datacap_posting_finished(target.deal.deal_id):
            raise MigrationError("V2 DataCap posting is not finished")
        inspector = SectorStatusInspector()
        if inspector.porep_market_contract() != self.view_helper.porep_market_contract():
            raise MigrationError("Sector status inspector belongs to a different V2 PoRep Market")
        for claim in claims:
            if claim.end_epoch < target.service.service_end_epoch:
                raise MigrationError(f"Claim {claim.claim_id} ends before V2 service end")
            partition = self.web3.state_sector_partition(pair.source.provider, claim.sector, tipset_key)
            deadline = int(partition.get("Deadline", partition.get("deadline", -1)))
            partition_index = int(partition.get("Partition", partition.get("partition", -1)))
            info = self.web3.state_sector_get_info(pair.source.provider, claim.sector, tipset_key)
            expiration = int((info or {}).get("Expiration", (info or {}).get("expiration", 0)))
            if expiration < target.service.service_end_epoch:
                raise MigrationError(f"Sector {claim.sector} expires before V2 service end")
            if not inspector.is_active(target.deal.deal_id, claim.sector, deadline, partition_index):
                raise MigrationError(f"Sector {claim.sector} is not active for V2 deal")
        return pair

    @staticmethod
    def next_action(pair: MigrationPair, plan: AdoptionPlan | None = None) -> str:
        state = pair.target.deal.state
        if state == PoRepMarketDealState.ACTIVE:
            return "V2 active and verified; operator closes V1"
        if state != PoRepMarketDealState.ACCEPTED:
            return f"operator review required for V2 state {state}"
        if not pair.target.deal.rail_id:
            return "client runs prepare-migration"
        if plan is not None and plan.extensions:
            return "client runs prepare-migration to adopt remaining claims"
        adapter = DataCapEvidenceAdapter(pair.target.deal.evidence_adapter_address)
        if not adapter.is_datacap_posting_finished(pair.target.deal.deal_id):
            return "client runs finish-migration after the SP extends sectors"
        return "service submits evidence, then admin activates payment"
