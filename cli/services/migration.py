from dataclasses import dataclass

import cbor2

from cli.services.contracts.datacap_evidence_adapter import DataCapEvidenceAdapter, DataCapEvidenceType, DataCapTransferParams
from cli.services.contracts.filecoin_pay import FileCoinPay, FileCoinPayRailView
from cli.services.contracts.legacy_porep_market import LegacyDeal, LegacyPoRepMarket
from cli.services.contracts.porep_market import PoRepMarket, PoRepMarketDealState
from cli.services.contracts.porep_market_view_helper import PoRepMarketDealView, PoRepMarketViewHelper
from cli.services.web3_service import ActorId, EthAddress, Web3Service

MAX_UINT64 = 2 ** 64 - 1
EPOCHS_IN_DAY = 2_880
# builtin-actors verifreg policy: a claim term may reach at most 5 years after the current epoch
MAXIMUM_VERIFIED_ALLOCATION_TERM = 5 * 365 * EPOCHS_IN_DAY
# keep the requested term below the actor limit so the transaction still passes if it lands a bit later
CLAIM_TERM_RESERVE_EPOCHS = EPOCHS_IN_DAY
DATACAP_PRECISION = 10 ** 18
VERIFIED_REGISTRY_ACTOR_ADDRESS = (b"\x00\x06",)
ADOPTION_BATCH_SIZE = 100
MAX_BPS = 10_000


class MigrationError(RuntimeError):
    pass


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

        piece = value("Data", "data")
        return cls(
            claim_id=claim_id,
            provider=ActorId(value("Provider", "provider")),
            client=ActorId(value("Client", "client")),
            data=str(piece["/"] if isinstance(piece, dict) else piece),
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
    registered_ids: frozenset[int]
    extensions: tuple[ClaimExtension, ...]

    @property
    def source_ids(self) -> frozenset[int]:
        return frozenset(claim.claim_id for claim in self.source_claims)

    @property
    def complete(self) -> bool:
        return not self.extensions and self.registered_ids == self.source_ids

    @property
    def operator_data(self) -> bytes:
        return claim_extension_cbor(self.extensions)

    @property
    def datacap_amount(self) -> int:
        return sum(extension.size for extension in self.extensions) * DATACAP_PRECISION

    def batches(self, size: int = ADOPTION_BATCH_SIZE) -> list["AdoptionPlan"]:
        if size <= 0:
            raise ValueError("Adoption batch size must be positive")
        return [
            AdoptionPlan(self.source_claims, self.registered_ids, self.extensions[offset:offset + size])
            for offset in range(0, len(self.extensions), size)
        ]


@dataclass(frozen=True)
class MigrationPair:
    source: LegacyDeal
    source_rail: FileCoinPayRailView
    target: PoRepMarketDealView


def claim_extension_cbor(extensions: list[ClaimExtension] | tuple[ClaimExtension, ...]) -> bytes:
    rows = []
    for extension in extensions:
        values = (int(extension.provider), extension.claim_id, extension.new_term_max)
        if any(value < 0 or value > MAX_UINT64 for value in values):
            raise MigrationError("Claim extension contains a value outside the CBOR uint64 range")
        rows.append(list(values))
    # verifreg operator data: [allocation requests, claim extension requests]
    return cbor2.dumps([[], rows], canonical=True)


def extension_term_max(claim: Claim, current_epoch: int) -> int:
    if claim.end_epoch <= current_epoch:
        raise MigrationError(f"V1 claim {claim.claim_id} expired at epoch {claim.end_epoch}")
    new_term_max = current_epoch + MAXIMUM_VERIFIED_ALLOCATION_TERM - claim.term_start - CLAIM_TERM_RESERVE_EPOCHS
    if new_term_max <= claim.term_max:
        raise MigrationError(
            f"V1 claim {claim.claim_id} already has term max {claim.term_max}, "
            f"nothing left to extend below the actor limit {new_term_max + CLAIM_TERM_RESERVE_EPOCHS}"
        )
    return new_term_max


def build_adoption_plan(source_claims: list[Claim], registered_ids: list[int], current_epoch: int) -> AdoptionPlan:
    source_ids = [claim.claim_id for claim in source_claims]
    if not source_ids or len(set(source_ids)) != len(source_ids):
        raise MigrationError("Source claim IDs are empty or duplicated")
    registered = [int(value) for value in registered_ids]
    if len(set(registered)) != len(registered):
        raise MigrationError("Target adapter contains duplicate claim IDs")
    foreign = set(registered) - set(source_ids)
    if foreign:
        raise MigrationError(f"Target adapter contains claim IDs that do not belong to the V1 deal: {sorted(foreign)}")

    extensions = tuple(
        ClaimExtension(claim.provider, claim.claim_id, extension_term_max(claim, current_epoch), claim.size)
        for claim in source_claims
        if claim.claim_id not in registered
    )
    return AdoptionPlan(tuple(source_claims), frozenset(registered), extensions)


def size_within_padding(allocated_bytes: int, requested_bytes: int, padding_bps: int) -> bool:
    return (requested_bytes * (MAX_BPS - padding_bps) <= allocated_bytes * MAX_BPS
            <= requested_bytes * (MAX_BPS + padding_bps))


class MigrationService:
    def __init__(self,
                 source_market: EthAddress,
                 source_chain_id: int,
                 web3: Web3Service | None = None,
                 view_helper: PoRepMarketViewHelper | None = None):
        self.web3 = web3 or Web3Service()
        connected_chain_id = self.web3.get_chain_id()
        if int(source_chain_id) != connected_chain_id:
            raise MigrationError(
                f"POREP_MARKET_V1_CHAIN_ID {source_chain_id} does not match the connected chain {connected_chain_id}"
            )
        self.source_market = LegacyPoRepMarket(EthAddress(source_market))
        self.view_helper = view_helper or PoRepMarketViewHelper()

    # V1 side

    def source_deal(self, deal_id: int) -> LegacyDeal:
        return self.source_market.get_deal(deal_id)

    def source_rail(self, source: LegacyDeal) -> FileCoinPayRailView:
        if not source.rail_id:
            raise MigrationError(f"V1 deal {source.deal_id} has no payment rail")
        return FileCoinPay().get_rail(source.rail_id)

    def qualify_source(self, source: LegacyDeal) -> FileCoinPayRailView:
        if source.state != LegacyDeal.COMPLETED:
            raise MigrationError(f"V1 deal {source.deal_id} is not Completed (state {source.state})")
        rail = self.source_rail(source)
        if rail.end_epoch:
            raise MigrationError(f"V1 deal {source.deal_id} rail {source.rail_id} is already terminated")
        if rail.payment_rate <= 0:
            raise MigrationError(f"V1 deal {source.deal_id} rail {source.rail_id} is not paying")
        return rail

    def paying_source_deals(self, client: EthAddress | None = None) -> list[LegacyDeal]:
        result = []
        for deal in self.source_market.get_deals():
            if client is not None and deal.client != client:
                continue
            if deal.state != LegacyDeal.COMPLETED or not deal.rail_id:
                continue
            rail = self.source_rail(deal)
            if rail.end_epoch == 0 and rail.payment_rate > 0:
                result.append(deal)
        return result

    def source_claims(self, source: LegacyDeal, tipset_key: list[dict] | None = None) -> list[Claim]:
        tipset_key = tipset_key or self.web3.get_tipset_key()
        legacy_client = self.source_market.get_client_contract()
        ids = legacy_client.allocation_ids(source.deal_id)
        if not ids or len(ids) != len(set(ids)):
            raise MigrationError(f"V1 deal {source.deal_id} has no claims or duplicate claim IDs")
        if legacy_client.allocated_size(source.deal_id) != source.size_bytes:
            raise MigrationError(f"V1 deal {source.deal_id} does not have the exact full claimed size")
        expected_client = legacy_client.address().to_actor_id()
        rpc_claims = self.web3.state_get_claims(source.provider, tipset_key=tipset_key)
        claims = []
        for claim_id in ids:
            raw = rpc_claims.get(str(claim_id))
            if raw is None:
                raise MigrationError(f"V1 claim {claim_id} is missing from provider {source.provider}")
            claim = Claim.from_rpc(claim_id, raw)
            if legacy_client.is_claim_terminated(claim_id):
                raise MigrationError(f"V1 claim {claim_id} is marked terminated in the V1 client contract")
            if claim.client != expected_client:
                raise MigrationError(f"V1 claim {claim_id} belongs to client actor {claim.client}, expected {expected_client}")
            if claim.provider != source.provider:
                raise MigrationError(f"V1 claim {claim_id} belongs to provider {claim.provider}, expected {source.provider}")
            if not claim.data or claim.size <= 0 or claim.sector < 0:
                raise MigrationError(f"V1 claim {claim_id} has invalid piece, size or sector data")
            claims.append(claim)
        if sum(claim.size for claim in claims) != source.size_bytes:
            raise MigrationError(f"V1 deal {source.deal_id} claim bytes do not equal the full deal size")
        return claims

    # V1/V2 pair

    def pair(self, target_deal_id: int, source_deal_id: int, require_paying: bool = True) -> MigrationPair:
        target = self.view_helper.get_deal_view(target_deal_id)
        source = self.source_deal(source_deal_id)
        if target.deal.client_address != source.client:
            raise MigrationError(
                f"V2 deal {target_deal_id} client {target.deal.client_address} differs from V1 deal {source_deal_id} client {source.client}"
            )
        if target.deal.provider_id != source.provider:
            raise MigrationError(
                f"V2 deal {target_deal_id} provider {target.deal.provider_id} differs from V1 deal {source_deal_id} provider {source.provider}"
            )
        rail = self.qualify_source(source) if require_paying else self.source_rail(source)
        return MigrationPair(source, rail, target)

    def adapter(self, pair: MigrationPair) -> DataCapEvidenceAdapter:
        adapter = DataCapEvidenceAdapter(pair.target.deal.evidence_adapter_address)
        if adapter.get_porep_market_contract_address() != self.view_helper.porep_market_contract():
            raise MigrationError("V2 evidence adapter belongs to a different PoRep Market")
        if adapter.evidence_type() != DataCapEvidenceType.VERIF_REG_CLAIMS:
            raise MigrationError("V2 deal does not use the VerifReg claims evidence adapter")
        return adapter

    @staticmethod
    def registered_ids(adapter: DataCapEvidenceAdapter, deal_id: int) -> list[int]:
        return adapter_claim_ids(adapter, deal_id)

    def check_target_size(self, pair: MigrationPair, claims: list[Claim]):
        claimed = sum(claim.size for claim in claims)
        requested = pair.target.terms.requested_size_bytes
        padding = PoRepMarket().get_deal_activation_padding()
        if not size_within_padding(claimed, requested, padding):
            raise MigrationError(
                f"V2 deal {pair.target.deal.deal_id} requested size {requested} is not within {padding / 100:.2f}% of the "
                f"V1 claimed size {claimed}; the admin has to fix the V2 manifest size before adoption"
            )

    def adoption_plan(self, pair: MigrationPair, require_operational: bool = True) -> AdoptionPlan:
        if pair.target.deal.state != PoRepMarketDealState.ACCEPTED:
            raise MigrationError(f"V2 deal {pair.target.deal.deal_id} is {pair.target.deal.state}, expected ACCEPTED")
        adapter = self.adapter(pair)
        if adapter.is_datacap_posting_finished(pair.target.deal.deal_id):
            raise MigrationError(f"V2 deal {pair.target.deal.deal_id} DataCap posting is already finished")
        if require_operational and not adapter.is_operational():
            raise MigrationError("V2 evidence adapter is not operational (DataCap transfers are disabled after NV29)")
        claims = self.source_claims(pair.source)
        self.check_target_size(pair, claims)
        registered = self.registered_ids(adapter, pair.target.deal.deal_id)
        plan = build_adoption_plan(claims, registered, self.web3.get_block_number())
        self._check_registered_bytes(adapter, pair.target.deal.deal_id, plan)
        return plan

    @staticmethod
    def _check_registered_bytes(adapter: DataCapEvidenceAdapter, deal_id: int, plan: AdoptionPlan):
        sizes = {claim.claim_id: claim.size for claim in plan.source_claims}
        expected = sum(sizes[claim_id] for claim_id in plan.registered_ids)
        actual = adapter.get_allocated_bytes(deal_id)
        if actual != expected:
            raise MigrationError(f"V2 adapter records {actual} bytes for the registered V1 claims, expected {expected}")

    @staticmethod
    def transfer_params(batch: AdoptionPlan) -> DataCapTransferParams:
        amount = batch.datacap_amount
        return DataCapTransferParams(
            to=VERIFIED_REGISTRY_ACTOR_ADDRESS,
            amount=(amount.to_bytes((amount.bit_length() + 7) // 8, "big"), False),
            operator_data=batch.operator_data,
        )

    def validate_batch_receipt(self, pair: MigrationPair, plan: AdoptionPlan, batch: AdoptionPlan):
        adapter = DataCapEvidenceAdapter(pair.target.deal.evidence_adapter_address)
        registered = set(self.registered_ids(adapter, pair.target.deal.deal_id))
        submitted = {extension.claim_id for extension in batch.extensions}
        if not submitted <= registered:
            raise MigrationError(f"Adapter did not register the submitted claims: {sorted(submitted - registered)}")
        if not registered <= plan.source_ids:
            raise MigrationError(f"Adapter registered claims outside the V1 deal: {sorted(registered - plan.source_ids)}")
        self._check_registered_bytes(adapter, pair.target.deal.deal_id, AdoptionPlan(plan.source_claims, frozenset(registered), ()))
        rpc_claims = self.web3.state_get_claims(pair.source.provider, tipset_key=self.web3.get_tipset_key())
        for extension in batch.extensions:
            raw = rpc_claims.get(str(extension.claim_id))
            if raw is None:
                raise MigrationError(f"V1 claim {extension.claim_id} disappeared after the batch landed")
            if Claim.from_rpc(extension.claim_id, raw).term_max < extension.new_term_max:
                raise MigrationError(f"V1 claim {extension.claim_id} was not extended to term max {extension.new_term_max}")

    # status

    def pair_by_claims(self, targets: list[PoRepMarketDealView], sources: list[LegacyDeal]) -> dict[int, int]:
        """Map V2 deal ID to V1 deal ID by the claim IDs the adapter already holds."""
        legacy_client = self.source_market.get_client_contract()
        source_ids = {source.deal_id: set(legacy_client.allocation_ids(source.deal_id)) for source in sources}
        result = {}
        for target in targets:
            if not target.deal.evidence_adapter_address:
                continue
            adapter = DataCapEvidenceAdapter(target.deal.evidence_adapter_address)
            registered = set(self.registered_ids(adapter, target.deal.deal_id))
            if not registered:
                continue
            for source_id, ids in source_ids.items():
                if registered & ids:
                    result[target.deal.deal_id] = source_id
                    break
        return result


def adapter_claim_ids(adapter: DataCapEvidenceAdapter, deal_id: int) -> list[int]:
    """Claim IDs the adapter holds for the deal: pending (allocation list) plus confirmed (claim list)."""
    pending = _all_adapter_ids(adapter.get_allocation_ids_per_deal, deal_id)
    confirmed = _all_adapter_ids(adapter.get_claim_ids, deal_id)
    overlap = set(pending) & set(confirmed)
    if overlap:
        raise MigrationError(f"Target adapter repeats IDs in pending and confirmed sets: {sorted(overlap)}")
    return pending + confirmed


def _all_adapter_ids(get_page, deal_id: int, page_size: int = 500) -> list[int]:
    ids: list[int] = []
    offset = 0
    while True:
        page, total = get_page(deal_id, offset, page_size)
        ids.extend(int(value) for value in page)
        offset += len(page)
        if not page or offset >= total:
            return ids
