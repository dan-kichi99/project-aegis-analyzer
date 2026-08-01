import struct
import zlib

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MAX_METADATA_BYTES = 2_000_000
_TIFF_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 7: 1}
_IMAGE_DESCRIPTION = 0x010E
_EXIF_IFD = 0x8769
_USER_COMMENT = 0x9286
_XP_TAGS = {0x9C9B, 0x9C9C, 0x9C9F}


def extract_image_metadata(content: bytes, detected_type: str) -> list[str]:
    """PNG TextまたはJPEG EXIFから安全に文字列を抽出する。"""
    try:
        if detected_type == "png":
            return _extract_png_text(content)
        if detected_type == "jpeg":
            return _extract_jpeg_exif(content)
    except (UnicodeError, ValueError, struct.error, zlib.error):
        return []
    return []


def _extract_png_text(content: bytes) -> list[str]:
    if not content.startswith(_PNG_SIGNATURE):
        return []

    values: list[str] = []
    offset = len(_PNG_SIGNATURE)
    while offset + 12 <= len(content):
        length = struct.unpack(">I", content[offset : offset + 4])[0]
        chunk_end = offset + 12 + length
        if length > _MAX_METADATA_BYTES or chunk_end > len(content):
            break

        chunk_type = content[offset + 4 : offset + 8]
        chunk_data = content[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", content[chunk_end - 4 : chunk_end])[0]
        if zlib.crc32(chunk_type + chunk_data) == expected_crc:
            value = _decode_png_text_chunk(chunk_type, chunk_data)
            if value:
                values.append(value)
        offset = chunk_end
        if chunk_type == b"IEND":
            break
    return values


def _decode_png_text_chunk(chunk_type: bytes, data: bytes) -> str | None:
    if chunk_type == b"tEXt":
        _, separator, text = data.partition(b"\x00")
        return text.decode("latin-1").strip() if separator else None

    if chunk_type == b"zTXt":
        _, separator, compressed = data.partition(b"\x00")
        if not separator or not compressed or compressed[0] != 0:
            return None
        decoded = _limited_decompress(compressed[1:])
        return decoded.decode("latin-1").strip() if decoded is not None else None

    if chunk_type != b"iTXt":
        return None

    _, separator, remainder = data.partition(b"\x00")
    if not separator or len(remainder) < 2:
        return None
    compression_flag, compression_method = remainder[:2]
    remainder = remainder[2:]
    _, separator, remainder = remainder.partition(b"\x00")
    if not separator:
        return None
    _, separator, text = remainder.partition(b"\x00")
    if not separator or compression_method != 0:
        return None
    if compression_flag == 1:
        text = _limited_decompress(text)
        if text is None:
            return None
    elif compression_flag != 0:
        return None
    return text.decode("utf-8").strip()


def _limited_decompress(data: bytes) -> bytes | None:
    decompressor = zlib.decompressobj()
    decoded = decompressor.decompress(data, _MAX_METADATA_BYTES + 1)
    if len(decoded) > _MAX_METADATA_BYTES or decompressor.unconsumed_tail:
        return None
    decoded += decompressor.flush()
    return decoded if len(decoded) <= _MAX_METADATA_BYTES else None


def _extract_jpeg_exif(content: bytes) -> list[str]:
    if not content.startswith(b"\xff\xd8"):
        return []

    offset = 2
    while offset + 4 <= len(content):
        if content[offset] != 0xFF:
            offset += 1
            continue
        marker = content[offset + 1]
        offset += 2
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(content):
            break
        segment_length = struct.unpack(">H", content[offset : offset + 2])[0]
        if segment_length < 2 or offset + segment_length > len(content):
            break
        segment = content[offset + 2 : offset + segment_length]
        if marker == 0xE1 and segment.startswith(b"Exif\x00\x00"):
            return _extract_tiff_values(segment[6:])
        offset += segment_length
    return []


def _extract_tiff_values(tiff: bytes) -> list[str]:
    if len(tiff) < 8 or tiff[:2] not in (b"II", b"MM"):
        return []
    endian = "<" if tiff[:2] == b"II" else ">"
    if struct.unpack(f"{endian}H", tiff[2:4])[0] != 42:
        return []
    first_ifd = struct.unpack(f"{endian}I", tiff[4:8])[0]
    return _read_ifd(tiff, first_ifd, endian, set())


def _read_ifd(
    tiff: bytes,
    offset: int,
    endian: str,
    visited: set[int],
) -> list[str]:
    if offset in visited or offset + 2 > len(tiff):
        return []
    visited.add(offset)
    count = struct.unpack(f"{endian}H", tiff[offset : offset + 2])[0]
    if count > 200 or offset + 2 + count * 12 > len(tiff):
        return []

    values: list[str] = []
    for index in range(count):
        start = offset + 2 + index * 12
        tag, value_type = struct.unpack(f"{endian}HH", tiff[start : start + 4])
        value_count = struct.unpack(f"{endian}I", tiff[start + 4 : start + 8])[0]
        value = _read_tiff_value(
            tiff,
            start,
            value_type,
            value_count,
            endian,
        )
        if value is None:
            continue
        if tag == _EXIF_IFD and len(value) == 4:
            child_offset = struct.unpack(f"{endian}I", value)[0]
            values.extend(_read_ifd(tiff, child_offset, endian, visited))
        elif tag == _IMAGE_DESCRIPTION:
            decoded = value.rstrip(b"\x00").decode("utf-8", errors="replace")
            if decoded.strip():
                values.append(decoded.strip())
        elif tag == _USER_COMMENT:
            decoded = _decode_user_comment(value)
            if decoded:
                values.append(decoded)
        elif tag in _XP_TAGS:
            decoded = value.decode("utf-16-le").rstrip("\x00").strip()
            if decoded:
                values.append(decoded)
    return values


def _read_tiff_value(
    tiff: bytes,
    entry_start: int,
    value_type: int,
    count: int,
    endian: str,
) -> bytes | None:
    unit_size = _TIFF_TYPE_SIZES.get(value_type)
    if unit_size is None or count > _MAX_METADATA_BYTES:
        return None
    size = unit_size * count
    if size > _MAX_METADATA_BYTES:
        return None
    if size <= 4:
        return tiff[entry_start + 8 : entry_start + 8 + size]
    value_offset = struct.unpack(
        f"{endian}I", tiff[entry_start + 8 : entry_start + 12]
    )[0]
    if value_offset + size > len(tiff):
        return None
    return tiff[value_offset : value_offset + size]


def _decode_user_comment(value: bytes) -> str | None:
    if value.startswith(b"ASCII\x00\x00\x00"):
        decoded = value[8:].rstrip(b"\x00").decode("ascii")
    elif value.startswith(b"UNICODE\x00"):
        payload = value[8:].rstrip(b"\x00")
        try:
            decoded = payload.decode("utf-16-be")
        except UnicodeDecodeError:
            decoded = payload.decode("utf-16-le")
    else:
        decoded = value.rstrip(b"\x00").decode("utf-8", errors="replace")
    return decoded.strip() or None
