import base64

CID_VERSION = 1
CODEC_RAW = 0x55
CODEC_FIL_COMMITMENT_UNSEALED = 0xF101
MH_FR32_SHA256_TRUNC254_PADBINTREE = 0x1011
MH_SHA2_256_TRUNC254_PADDED = 0x1012


def _encode_uvarint(value: int) -> bytes:
    if value < 0:
        raise ValueError("uvarint cannot encode negative value")

    result = bytearray()

    while True:
        byte = value & 0x7F
        value >>= 7

        if value:
            result.append(byte | 0x80)
        else:
            result.append(byte)
            return bytes(result)


def _decode_uvarint(data: bytes, offset: int = 0) -> tuple[int, int]:
    value = 0
    shift = 0

    while True:
        if offset >= len(data):
            raise ValueError("Unexpected end of uvarint")

        byte = data[offset]
        offset += 1

        value |= (byte & 0x7F) << shift

        if byte < 0x80:
            return value, offset

        shift += 7

        if shift >= 64:
            raise ValueError("uvarint overflow")


def _decode_base32_cid(cid: str) -> bytes:
    if not cid.startswith("b"):
        raise ValueError(f"Unsupported CID multibase: expected base32 CID, got {cid!r}")

    encoded = cid[1:].upper()
    encoded += "=" * ((8 - len(encoded) % 8) % 8)

    try:
        return base64.b32decode(encoded)
    except ValueError as e:
        raise ValueError(f"Invalid base32 CID: {cid!r}") from e


def _encode_base32_cid(data: bytes) -> str:
    return (
            "b"
            + base64.b32encode(data)
            .decode("ascii")
            .lower()
            .rstrip("=")
    )


def _extract_piece_commitment_v1(piece_cid_v1: str) -> bytes:
    data = _decode_base32_cid(piece_cid_v1)
    offset = 0

    version, offset = _decode_uvarint(data, offset)
    codec, offset = _decode_uvarint(data, offset)
    mh_code, offset = _decode_uvarint(data, offset)
    digest_size, offset = _decode_uvarint(data, offset)

    if version != CID_VERSION:
        raise ValueError(f"Unsupported CID version: {version}")

    if codec != CODEC_FIL_COMMITMENT_UNSEALED:
        raise ValueError(f"Expected fil-commitment-unsealed codec 0x{CODEC_FIL_COMMITMENT_UNSEALED:x}, got 0x{codec:x}")

    if mh_code != MH_SHA2_256_TRUNC254_PADDED:
        raise ValueError(f"Expected sha2-256-trunc254-padded multihash 0x{MH_SHA2_256_TRUNC254_PADDED:x}, got 0x{mh_code:x}")

    if digest_size != 32:
        raise ValueError(f"Expected 32-byte commitment, got {digest_size}")

    digest = data[offset:offset + digest_size]

    if len(digest) != digest_size:
        raise ValueError("Truncated piece CID")

    if offset + digest_size != len(data):
        raise ValueError("Unexpected trailing bytes in piece CID")

    return digest


def _piece_tree_height_and_padding(payload_size: int) -> tuple[int, int]:
    if payload_size < 127:
        raise ValueError(f"Payload size must be at least 127 bytes, got {payload_size}")

    # Equivalent to ceil(payload_size * 128 / 127)
    fr32_data_size = payload_size * 128 // 127

    if fr32_data_size * 127 != payload_size * 128:
        fr32_data_size += 1

    if fr32_data_size <= 32:
        tree_height = 0
    else:
        # ceil(log2(fr32_data_size)) - log2(32)
        tree_height = (fr32_data_size - 1).bit_length() - 5

    padded_fr32_size = 32 << tree_height
    padded_data_size = padded_fr32_size // 128 * 127

    padding = padded_data_size - payload_size

    if padding < 0:
        raise RuntimeError(f"Invalid calculated padding: {padding}")

    return tree_height, padding


def padded_piece_size_for_payload(payload_size: int) -> int:
    tree_height, _ = _piece_tree_height_and_padding(payload_size)
    return 32 << tree_height


def cid_to_bytes(cid: str) -> bytes:
    return _decode_base32_cid(cid)


def piece_cid_v1_to_v2(piece_cid_v1: str, payload_size: int) -> str:
    """
    Convert Filecoin PieceCID v1 + raw payload size into PieceCID v2.

    Equivalent to go-fil-commcid PieceCidV2FromV1().
    """

    commitment = _extract_piece_commitment_v1(piece_cid_v1)
    tree_height, padding = _piece_tree_height_and_padding(payload_size)

    digest = (
            _encode_uvarint(padding)
            + bytes([tree_height])
            + commitment
    )

    multihash = (
            _encode_uvarint(MH_FR32_SHA256_TRUNC254_PADBINTREE)
            + _encode_uvarint(len(digest))
            + digest
    )

    cid = (
            _encode_uvarint(CID_VERSION)
            + _encode_uvarint(CODEC_RAW)
            + multihash
    )

    return _encode_base32_cid(cid)
