import struct
import zlib

from app.file.png_metadata_result import (
    PngChunkItem,
    PngMetadataItem,
    PngMetadataResult,
    PngTrailingDataResult,
)
from app.judge.flag_extractor import FlagExtractor

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_MAX_FILE_SIZE = 50_000_000
_MAX_CHUNKS = 500
_MAX_CHUNK_LENGTH = 20_000_000
_MAX_METADATA_ITEMS = 200
_MAX_KEY_LENGTH = 200
_MAX_VALUE_LENGTH = 2_000
_MAX_PREVIEW_LENGTH = 500
_MAX_ZLIB_OUTPUT = 1_000_000
_MAX_TRAILING_BYTES = 1_000_000
_MAX_STRINGS = 100
_MAX_FLAGS = 100
_MIN_STRING_LENGTH = 4
_MAX_STRING_LENGTH = 300

_CRITICAL_CHUNKS = frozenset({"IHDR", "PLTE", "IDAT", "IEND"})
_ANCILLARY_CHUNKS = frozenset(
    {"tEXt", "zTXt", "iTXt", "pHYs", "tIME", "gAMA", "sRGB", "cHRM", "eXIf"}
)
_KNOWN_CHUNK_TYPES = _CRITICAL_CHUNKS | _ANCILLARY_CHUNKS
_TEXT_CHUNKS = frozenset({"tEXt", "zTXt", "iTXt"})

_VALID_COLOR_BIT_DEPTHS = {
    0: {1, 2, 4, 8, 16},
    2: {8, 16},
    3: {1, 2, 4, 8},
    4: {8, 16},
    6: {8, 16},
}

_IMPORTANT_KEYWORDS = (
    "flag",
    "password",
    "secret",
    "key",
    "hint",
    "comment",
    "author",
    "creator",
    "description",
    "title",
    "software",
    "source",
    "encoded",
    "base64",
    "xor",
    "caesar",
)

_MAGIC_SIGNATURES = (
    (b"PK\x03\x04", "ZIP"),
    (b"PK\x05\x06", "ZIP"),
    (b"%PDF-", "PDF"),
    (b"\x7fELF", "ELF"),
    (b"MZ", "PE"),
    (_PNG_SIGNATURE, "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x1f\x8b", "GZIP"),
)

PNG_METADATA_PREFIX = "__AEGIS_PNG_METADATA__:"
PNG_WARNING_PREFIX = "__AEGIS_PNG_WARNING__:"
PNG_TRAILING_PREFIX = "__AEGIS_PNG_TRAILING__:"
PNG_FLAG_PREFIX = "__AEGIS_PNG_FLAG__:"

_EMPTY_RESULT = PngMetadataResult(
    valid_signature=False,
    width=None,
    height=None,
    chunks=(),
    metadata_items=(),
    warnings=(),
    flag_candidates=(),
    trailing_data=None,
    truncated=False,
)


def png_metadata_summary_strings(result: PngMetadataResult) -> list[str]:
    """PngMetadataResultを予約prefix付きの安全なsummary文字列へ変換する。"""
    if not result.valid_signature:
        return []
    values: list[str] = []
    if result.width is not None and result.height is not None:
        values.append(
            f"{PNG_METADATA_PREFIX}width={result.width} height={result.height}"
        )
    for item in result.metadata_items:
        values.append(
            f"{PNG_METADATA_PREFIX}{item.source} key={item.key} "
            f"value={item.value_preview}"
        )
    for warning in result.warnings:
        values.append(f"{PNG_WARNING_PREFIX}{warning}")
    if result.trailing_data is not None:
        magic = result.trailing_data.detected_magic or "unknown"
        values.append(
            f"{PNG_TRAILING_PREFIX}size={result.trailing_data.size} magic={magic}"
        )
    for flag in result.flag_candidates:
        values.append(f"{PNG_FLAG_PREFIX}candidate={flag}")
    return values


class PngMetadataAnalyzer:
    """PNGの構造・テキストメタデータ・CRC・IEND後データを安全に解析する。"""

    def __init__(self, flag_extractor: FlagExtractor | None = None) -> None:
        self._flag_extractor = flag_extractor or FlagExtractor()

    def analyze(self, content: bytes) -> PngMetadataResult:
        if not content.startswith(_PNG_SIGNATURE):
            return _EMPTY_RESULT
        if len(content) > _MAX_FILE_SIZE:
            return PngMetadataResult(
                valid_signature=True,
                width=None,
                height=None,
                chunks=(),
                metadata_items=(),
                warnings=("ファイルサイズが上限（50MB）を超えているため解析を中止しました。",),
                flag_candidates=(),
                trailing_data=None,
                truncated=True,
            )

        warnings: list[str] = []
        chunks: list[PngChunkItem] = []
        metadata_items: list[PngMetadataItem] = []
        flag_candidates: list[str] = []
        seen_flags: set[str] = set()
        truncated = False

        ihdr_seen = False
        iend_seen = False
        first_iend_end: int | None = None
        ihdr_fields: dict[str, int] | None = None

        offset = len(_PNG_SIGNATURE)
        chunk_index = 0
        while offset < len(content):
            if chunk_index >= _MAX_CHUNKS:
                warnings.append("chunk数が上限を超えたため解析を打ち切りました。")
                truncated = True
                break
            if offset + 8 > len(content):
                warnings.append(f"offset 0x{offset:X} でchunkが切り詰められています。")
                truncated = True
                break

            length = struct.unpack_from(">I", content, offset)[0]
            chunk_type_bytes = content[offset + 4 : offset + 8]
            chunk_type = chunk_type_bytes.decode("latin-1")
            data_start = offset + 8

            if length > _MAX_CHUNK_LENGTH:
                warnings.append(
                    f"chunk「{chunk_type}」(offset 0x{offset:X}) の"
                    "lengthが異常に大きいため解析を打ち切りました。"
                )
                truncated = True
                break

            data_end = data_start + length
            crc_end = data_end + 4
            if crc_end > len(content):
                warnings.append(
                    f"chunk「{chunk_type}」(offset 0x{offset:X}) が"
                    "ファイル範囲外または切り詰められています。"
                )
                truncated = True
                break

            chunk_data = content[data_start:data_end]
            crc_actual = struct.unpack_from(">I", content, data_end)[0]
            crc_expected = zlib.crc32(chunk_type_bytes + chunk_data) & 0xFFFFFFFF
            crc_valid = crc_expected == crc_actual
            if not crc_valid:
                warnings.append(
                    f"chunk「{chunk_type}」(offset 0x{offset:X}) でCRC不一致を検出しました。"
                )

            critical = (chunk_type_bytes[0] & 0x20) == 0
            known = chunk_type in _KNOWN_CHUNK_TYPES
            if critical and not known:
                warnings.append(f"未知のcritical chunk「{chunk_type}」を検出しました。")

            if chunk_type == "IHDR":
                if ihdr_seen:
                    warnings.append("IHDRが複数回出現しています。")
                elif chunk_index != 0:
                    warnings.append("IHDRが先頭chunkではありません。")
                ihdr_seen = True
                ihdr_fields = self._parse_ihdr(chunk_data, warnings)

            if chunk_type == "IEND":
                if iend_seen:
                    warnings.append("IENDが複数回出現しています。")
                if length != 0:
                    warnings.append("IENDのlengthが0ではありません。")
                if not iend_seen:
                    first_iend_end = crc_end
                iend_seen = True

            detail = self._build_detail(chunk_type, chunk_data)
            chunks.append(
                PngChunkItem(
                    chunk_type=chunk_type,
                    offset=offset,
                    length=length,
                    crc_expected=crc_expected,
                    crc_actual=crc_actual,
                    crc_valid=crc_valid,
                    critical=critical,
                    known=known,
                    detail=detail,
                )
            )

            if chunk_type in _TEXT_CHUNKS:
                if len(metadata_items) >= _MAX_METADATA_ITEMS:
                    truncated = True
                else:
                    item = self._parse_text_chunk(
                        chunk_type, chunk_data, offset, warnings
                    )
                    if item is not None:
                        metadata_items.append(item)
                        self._merge_flags(
                            flag_candidates, seen_flags, item.flag_candidates
                        )

            offset = crc_end
            chunk_index += 1

        if not ihdr_seen:
            warnings.append("IHDRが見つかりません。")
        if not iend_seen:
            warnings.append("IENDが見つかりません。")

        trailing_data = None
        if iend_seen and first_iend_end is not None and first_iend_end < len(content):
            trailing_data = self._analyze_trailing(content, first_iend_end)
            if trailing_data is not None:
                self._merge_flags(
                    flag_candidates, seen_flags, trailing_data.flag_candidates
                )

        width = ihdr_fields["width"] if ihdr_fields else None
        height = ihdr_fields["height"] if ihdr_fields else None
        bit_depth = ihdr_fields["bit_depth"] if ihdr_fields else None
        color_type = ihdr_fields["color_type"] if ihdr_fields else None
        compression_method = ihdr_fields["compression_method"] if ihdr_fields else None
        filter_method = ihdr_fields["filter_method"] if ihdr_fields else None
        interlace_method = ihdr_fields["interlace_method"] if ihdr_fields else None

        return PngMetadataResult(
            valid_signature=True,
            width=width,
            height=height,
            chunks=tuple(chunks),
            metadata_items=tuple(metadata_items),
            warnings=tuple(warnings),
            flag_candidates=tuple(flag_candidates[:_MAX_FLAGS]),
            trailing_data=trailing_data,
            truncated=truncated,
            bit_depth=bit_depth,
            color_type=color_type,
            compression_method=compression_method,
            filter_method=filter_method,
            interlace_method=interlace_method,
        )

    def _parse_ihdr(
        self, data: bytes, warnings: list[str]
    ) -> dict[str, int] | None:
        if len(data) != 13:
            warnings.append("IHDRのlengthが13ではありません。")
            return None
        width, height, bit_depth, color_type, compression_method, filter_method, interlace_method = (
            struct.unpack(">IIBBBBB", data)
        )
        if width == 0:
            warnings.append("widthが0です。")
        if height == 0:
            warnings.append("heightが0です。")
        allowed_depths = _VALID_COLOR_BIT_DEPTHS.get(color_type)
        if allowed_depths is None or bit_depth not in allowed_depths:
            warnings.append(
                f"bit_depth={bit_depth}とcolor_type={color_type}の組み合わせが不正です。"
            )
        if compression_method != 0:
            warnings.append("compression methodが0ではありません。")
        if filter_method != 0:
            warnings.append("filter methodが0ではありません。")
        if interlace_method not in (0, 1):
            warnings.append("interlace methodが0または1ではありません。")
        return {
            "width": width,
            "height": height,
            "bit_depth": bit_depth,
            "color_type": color_type,
            "compression_method": compression_method,
            "filter_method": filter_method,
            "interlace_method": interlace_method,
        }

    def _build_detail(self, chunk_type: str, data: bytes) -> str:
        if chunk_type == "IHDR":
            if len(data) == 13:
                w, h, bd, ct, cm, fm, im = struct.unpack(">IIBBBBB", data)
                return (
                    f"width={w} height={h} bit_depth={bd} color_type={ct} "
                    f"compression={cm} filter={fm} interlace={im}"
                )
            return f"invalid length ({len(data)} bytes)"
        if chunk_type == "PLTE":
            return f"{len(data)} bytes ({len(data) // 3} palette entries)"
        if chunk_type == "IDAT":
            return f"{len(data)} bytes (image data, not stored)"
        if chunk_type == "IEND":
            return "end marker"
        if chunk_type == "pHYs" and len(data) == 9:
            x, y, unit = struct.unpack(">IIB", data)
            return f"pixels_per_unit_x={x} pixels_per_unit_y={y} unit_specifier={unit}"
        if chunk_type == "tIME" and len(data) == 7:
            year, month, day, hour, minute, second = struct.unpack(">HBBBBB", data)
            return (
                f"{year:04d}-{month:02d}-{day:02d} "
                f"{hour:02d}:{minute:02d}:{second:02d}"
            )
        if chunk_type == "gAMA" and len(data) == 4:
            gamma_int = struct.unpack(">I", data)[0]
            display = gamma_int / 100_000 if gamma_int else 0.0
            return f"gamma={gamma_int} (display={display:.5f})"
        if chunk_type == "sRGB" and len(data) == 1:
            return f"rendering_intent={data[0]}"
        if chunk_type == "eXIf":
            byte_order = data[:2]
            order = (
                byte_order.decode("ascii")
                if byte_order in (b"II", b"MM")
                else "unknown"
            )
            return f"payload_size={len(data)} byte_order={order}"
        return f"{len(data)} bytes"

    def _parse_text_chunk(
        self,
        chunk_type: str,
        data: bytes,
        offset: int,
        warnings: list[str],
    ) -> PngMetadataItem | None:
        if chunk_type == "tEXt":
            return self._parse_text(data, offset)
        if chunk_type == "zTXt":
            return self._parse_ztxt(data, offset, warnings)
        return self._parse_itxt(data, offset, warnings)

    def _parse_text(self, data: bytes, offset: int) -> PngMetadataItem | None:
        keyword_bytes, separator, text_bytes = data.partition(b"\x00")
        if not separator or not keyword_bytes:
            return None
        keyword = keyword_bytes.decode("latin-1")[:_MAX_KEY_LENGTH]
        value = text_bytes.decode("latin-1")
        return self._build_item("tEXt", keyword, value, offset, compressed=False)

    def _parse_ztxt(
        self, data: bytes, offset: int, warnings: list[str]
    ) -> PngMetadataItem | None:
        keyword_bytes, separator, remainder = data.partition(b"\x00")
        if not separator or not keyword_bytes or not remainder:
            return None
        if remainder[0] != 0:
            warnings.append(
                f"zTXt「{keyword_bytes.decode('latin-1', errors='replace')}」の"
                "compression methodが0ではないため無視しました。"
            )
            return None
        decoded = self._limited_decompress(remainder[1:])
        if decoded is None:
            warnings.append(
                f"zTXt「{keyword_bytes.decode('latin-1', errors='replace')}」の"
                "展開に失敗またはサイズ上限を超えたため無視しました。"
            )
            return None
        keyword = keyword_bytes.decode("latin-1")[:_MAX_KEY_LENGTH]
        value = decoded.decode("latin-1")
        return self._build_item("zTXt", keyword, value, offset, compressed=True)

    def _parse_itxt(
        self, data: bytes, offset: int, warnings: list[str]
    ) -> PngMetadataItem | None:
        keyword_bytes, separator, remainder = data.partition(b"\x00")
        if not separator or not keyword_bytes or len(remainder) < 2:
            return None
        compression_flag = remainder[0]
        compression_method = remainder[1]
        remainder = remainder[2:]
        if compression_flag not in (0, 1) or compression_method != 0:
            return None
        _language, separator, remainder = remainder.partition(b"\x00")
        if not separator:
            return None
        translated_bytes, separator, text_bytes = remainder.partition(b"\x00")
        if not separator:
            return None

        if compression_flag == 1:
            decompressed = self._limited_decompress(text_bytes)
            if decompressed is None:
                warnings.append(
                    f"iTXt「{keyword_bytes.decode('latin-1', errors='replace')}」の"
                    "展開に失敗またはサイズ上限を超えたため無視しました。"
                )
                return None
            text_bytes = decompressed

        try:
            value = text_bytes.decode("utf-8")
            translated_keyword = translated_bytes.decode("utf-8")
        except UnicodeDecodeError:
            warnings.append(
                f"iTXt (offset 0x{offset:X}) のtextがUTF-8として不正なため無視しました。"
            )
            return None

        keyword = keyword_bytes.decode("latin-1")[:_MAX_KEY_LENGTH]
        key_for_display = translated_keyword or keyword
        return self._build_item(
            "iTXt",
            key_for_display,
            value,
            offset,
            compressed=(compression_flag == 1),
            extra_keyword=keyword,
        )

    def _build_item(
        self,
        source: str,
        keyword: str,
        value: str,
        offset: int,
        *,
        compressed: bool,
        extra_keyword: str | None = None,
    ) -> PngMetadataItem:
        truncated = len(value) > _MAX_VALUE_LENGTH
        limited_value = value[:_MAX_VALUE_LENGTH]
        preview = limited_value[:_MAX_PREVIEW_LENGTH]
        if len(limited_value) > _MAX_PREVIEW_LENGTH:
            truncated = True

        important = self._is_important(keyword) or (
            extra_keyword is not None and self._is_important(extra_keyword)
        )

        flags: list[str] = []
        seen: set[str] = set()
        for candidate in (keyword, extra_keyword, limited_value):
            if candidate is None:
                continue
            self._merge_flags(flags, seen, self._flag_extractor.extract_all(candidate))

        return PngMetadataItem(
            source=source,
            key=keyword,
            value_preview=preview,
            offset=offset,
            compressed=compressed,
            important=important,
            flag_candidates=tuple(flags[:_MAX_FLAGS]),
            truncated=truncated,
        )

    @staticmethod
    def _is_important(keyword: str) -> bool:
        lowered = keyword.lower()
        return any(word in lowered for word in _IMPORTANT_KEYWORDS)

    @staticmethod
    def _merge_flags(
        target: list[str], seen: set[str], candidates: tuple[str, ...]
    ) -> None:
        for flag in candidates:
            if flag not in seen and len(target) < _MAX_FLAGS:
                seen.add(flag)
                target.append(flag)

    @staticmethod
    def _limited_decompress(data: bytes) -> bytes | None:
        decompressor = zlib.decompressobj()
        try:
            decoded = decompressor.decompress(data, _MAX_ZLIB_OUTPUT + 1)
            if len(decoded) > _MAX_ZLIB_OUTPUT or decompressor.unconsumed_tail:
                return None
            decoded += decompressor.flush()
        except zlib.error:
            return None
        return decoded if len(decoded) <= _MAX_ZLIB_OUTPUT else None

    def _analyze_trailing(
        self, content: bytes, start_offset: int
    ) -> PngTrailingDataResult | None:
        remaining = content[start_offset:]
        if not remaining:
            return None
        size = len(remaining)
        held = remaining[:_MAX_TRAILING_BYTES]
        truncated = size > _MAX_TRAILING_BYTES
        preview = held[:_MAX_PREVIEW_LENGTH].decode("latin-1")
        magic = self._detect_magic(held)
        strings = self._extract_ascii_strings(held)

        flags: list[str] = []
        seen: set[str] = set()
        self._merge_flags(flags, seen, self._flag_extractor.extract_all(preview))
        for value in strings:
            self._merge_flags(flags, seen, self._flag_extractor.extract_all(value))

        return PngTrailingDataResult(
            offset=start_offset,
            size=size,
            preview=preview,
            detected_magic=magic,
            strings=tuple(strings),
            flag_candidates=tuple(flags[:_MAX_FLAGS]),
            truncated=truncated,
        )

    @staticmethod
    def _detect_magic(data: bytes) -> str | None:
        for signature, name in _MAGIC_SIGNATURES:
            if data.startswith(signature):
                return name
        return None

    @staticmethod
    def _extract_ascii_strings(data: bytes) -> list[str]:
        results: list[str] = []
        current: list[str] = []
        for byte in data:
            if 0x20 <= byte <= 0x7E:
                current.append(chr(byte))
                continue
            if len(current) >= _MIN_STRING_LENGTH:
                results.append("".join(current)[:_MAX_STRING_LENGTH])
                if len(results) >= _MAX_STRINGS:
                    return results
            current = []
        if len(current) >= _MIN_STRING_LENGTH and len(results) < _MAX_STRINGS:
            results.append("".join(current)[:_MAX_STRING_LENGTH])
        return results
