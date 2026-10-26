from cli import utils
from cli.services.contracts.evidence_adapter import EvidenceAdapter
from cli.services.web3_service import ActorId, EthAddress, FilAddress


# @notice Compact per-deal progress for the committed piece set.
# @param providerActorId Provider authenticated by the first accepted callback.
# @param pieceCount Number of committed pieces.
# @param acceptedPieceCount Number of unique accepted piece indexes.
# @param activated Whether PoRep Market consumed the completed receipt.
# @param minimumCommitmentEpoch Lowest commitment epoch across accepted pieces.
# @param acceptedBytes Sum of padded sizes for unique accepted indexes.
@utils.json_dataclass()
class SectorManifestReceipt:
    provider_id: ActorId | None
    piece_count: int
    accepted_piece_count: int
    activated: bool
    minimum_commitment_epoch: int
    accepted_bytes: int

    def __post_init__(self):
        self.provider_id = ActorId(self.provider_id) if self.provider_id else None

    @staticmethod
    def from_web3(data) -> "SectorManifestReceipt":
        provider_id = int(data[0])

        # empty object is useful here, so we return it instead of throwing "not found" error
        # noinspection PyArgumentList
        return SectorManifestReceipt(
            provider_id=ActorId(provider_id) if provider_id else None,
            piece_count=int(data[1]),
            accepted_piece_count=int(data[2]),
            activated=bool(data[3]),
            minimum_commitment_epoch=int(data[4]),
            accepted_bytes=int(data[5]),
        )


class SectorEvidenceAdapter(EvidenceAdapter):
    def __init__(self, contract_address: EthAddress | FilAddress):
        super().__init__(contract_address, self.abi_dir() / "SectorEvidenceAdapter.json")

    # @notice Returns compact piece-set progress for one deal.
    # @param dealId PoRep Market deal ID.
    # @return receipt Stored progress receipt.
    def get_manifest_receipt(self, deal_id: int) -> SectorManifestReceipt:
        return SectorManifestReceipt.from_web3(self.call_contract(self.contract.functions.getManifestReceipt(deal_id)))

    # @notice Returns whether one piece index has already been accepted for a deal.
    # @param dealId PoRep Market deal ID.
    # @param pieceIndex Zero-based piece index.
    # @return accepted Whether a placement is stored for this index.
    def is_piece_accepted(self, deal_id: int, piece_index: int) -> bool:
        return self.call_contract(self.contract.functions.isPieceAccepted(deal_id, piece_index))
