import click
import multibase
from eth_abi import encode
from hexbytes import HexBytes
from web3 import Web3

from cli import utils

_VERSION = 1
_LEAF_DOMAIN = Web3.keccak(text="PoRepMarket.PieceSet.Leaf")
_NODE_DOMAIN = Web3.keccak(text="PoRepMarket.PieceSet.Node")
_EMPTY_DOMAIN = Web3.keccak(text="PoRepMarket.PieceSet.Empty")
_COMMITMENT_DOMAIN = Web3.keccak(text="PoRepMarket.PieceSet.Commitment")
_EMPTY_LEAF = Web3.keccak(encode(["bytes32", "uint8"], [_EMPTY_DOMAIN, _VERSION]))

_COMMP_CID_PREFIX = bytes.fromhex("0181e203922020")
_MAX_UINT32 = 2 ** 32 - 1
_MAX_UINT64 = 2 ** 64 - 1


@utils.json_dataclass()
class PieceSetRow:
    index: int
    piece_cid: str
    digest: HexBytes
    padded_size: int


class PieceSet:
    def __init__(self, pieces: list[dict]):
        rows = sorted((_parse_piece(piece) for piece in pieces), key=lambda row: (row[1], row[2]))

        if not rows:
            raise click.ClickException("Piece set must contain at least one piece")

        if len(rows) > _MAX_UINT32:
            raise click.ClickException(f"Piece set is too large: {len(rows)} pieces")

        for previous, current in zip(rows, rows[1:]):
            if previous[1:] == current[1:]:
                raise click.ClickException(f"Duplicate piece in manifest: {current[0]} with pieceSize {current[2]}")

        # noinspection PyArgumentList
        self.rows = [PieceSetRow(index=index, piece_cid=cid, digest=HexBytes(digest), padded_size=size)
                     for index, (cid, digest, size) in enumerate(rows)]

        self.size_bytes = sum(row.padded_size for row in self.rows)
        self._levels = _build_tree([_leaf(row) for row in self.rows])

    def piece_count(self) -> int:
        return len(self.rows)

    def root(self) -> HexBytes:
        return HexBytes(self._levels[-1][0])

    def commitment(self) -> HexBytes:
        return Web3.keccak(encode(["bytes32", "uint8", "uint32", "uint256", "bytes32"],
                                  [_COMMITMENT_DOMAIN, _VERSION, self.piece_count(), self.size_bytes, self.root()]))

    def proof(self, index: int) -> list[HexBytes]:
        return [HexBytes(level[(index >> depth) ^ 1]) for depth, level in enumerate(self._levels[:-1])]

    def notification_payload(self, deal_id: int, index: int) -> HexBytes:
        return HexBytes(encode(["uint256", "uint32", "uint32", "bytes32[]"],
                               [deal_id, index, self.piece_count(), self.proof(index)]))


def _parse_piece(piece: dict) -> tuple[str, bytes, int]:
    cid = piece["pieceCid"]
    size = int(piece["pieceSize"])

    try:
        cid_bytes = bytes(multibase.decode(cid))
    except Exception as e:
        raise click.ClickException(f"Invalid piece CID '{cid}': {e}") from e

    if len(cid_bytes) != len(_COMMP_CID_PREFIX) + 32 or not cid_bytes.startswith(_COMMP_CID_PREFIX):
        raise click.ClickException(f"Unsupported piece CID '{cid}': expected CIDv1 CommP (baga...) piece CID")

    if not 0 < size <= _MAX_UINT64:
        raise click.ClickException(f"Invalid pieceSize {size} for piece {cid}")

    return cid, cid_bytes[len(_COMMP_CID_PREFIX):], size


def _leaf(row: PieceSetRow) -> bytes:
    return Web3.keccak(encode(["bytes32", "uint8", "uint32", "bytes32", "uint64"],
                              [_LEAF_DOMAIN, _VERSION, row.index, bytes(row.digest), row.padded_size]))


def _node(left: bytes, right: bytes) -> bytes:
    return Web3.keccak(encode(["bytes32", "bytes32", "bytes32"], [_NODE_DOMAIN, left, right]))


def _build_tree(leaves: list[bytes]) -> list[list[bytes]]:
    width = 1

    while width < len(leaves):
        width *= 2

    levels = [leaves + [_EMPTY_LEAF] * (width - len(leaves))]

    while len(levels[-1]) > 1:
        level = levels[-1]
        levels.append([_node(level[i], level[i + 1]) for i in range(0, len(level), 2)])

    return levels
