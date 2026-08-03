import re
import struct

from app.file.wav_static_result import (
    WavChunkItem,
    WavMetadataItem,
    WavStaticResult,
    WavTrailingDataResult,
)
from app.judge.flag_extractor import FlagExtractor

_RIFF_MAGIC = b"RIFF"
_WAVE_MAGIC = b"WAVE"

_MAX_FILE_SIZE = 50_000_000
_MAX_CHUNKS = 500
_MAX_METADATA_ITEMS = 200
_MAX_UNKNOWN_SCAN_BYTES = 65_536
_MAX_TRAILING_BYTES = 1_000_000
_MAX_PREVIEW = 500
_MAX_VALUE_LENGTH = 2_000
_MAX_STRINGS = 100
_MAX_FLAGS = 100
_MIN_STRING_LENGTH = 4
_MAX_STRING_LENGTH = 300
_MAX_IXML_BYTES = 1_000_000
_MAX_ID3_BYTES = 1_000_000

_KNOWN_CHUNKS = frozenset(
    {
        "fmt ",
        "data",
        "LIST",
        "JUNK",
        "PAD ",
        "fact",
        "cue ",
        "smpl",
        "bext",
        "iXML",
        "id3 ",
        "ID3 ",
        "DISP",
    }
)
_UNKNOWN_SCAN_CHUNKS = frozenset({"JUNK", "PAD "})

_INFO_KEYS = {
    "INAM": "title",
    "IART": "artist",
    "ICMT": "comment",
    "ICOP": "copyright",
    "ICRD": "date",
    "IGNR": "genre",
    "ISFT": "software",
    "IPRD": "product",
    "ITRK": "track",
    "IENG": "engineer",
    "ISBJ": "subject",
    "IKEY": "keywords",
}

_FORMAT_NAMES = {
    1: "PCM",
    3: "IEEE Float",
    6: "A-law",
    7: "μ-law",
    0xFFFE: "WAVE_FORMAT_EXTENSIBLE",
}

_IXML_TAGS = (
    "PROJECT",
    "SCENE",
    "TAKE",
    "NOTE",
    "TAPE",
    "FILE_SET",
    "TRACK_LIST",
    "SPEED",
    "TIMECODE_RATE",
)

_ID3_TEXT_FRAMES = ("TIT2", "TPE1", "COMM", "TXXX", "TALB", "TCON", "TCOP")

_IMPORTANT_KEYWORDS = (
    "flag",
    "password",
    "secret",
    "key",
    "hint",
    "comment",
    "author",
    "artist",
    "title",
    "copyright",
    "keyword",
    "hidden",
    "encoded",
    "base64",
    "xor",
    "caesar",
    "subject",
)

_MAGIC_SIGNATURES = (
    (b"PK\x03\x04", "ZIP"),
    (b"PK\x05\x06", "ZIP"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"%PDF-", "PDF"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x7fELF", "ELF"),
    (b"MZ", "PE"),
    (b"\x1f\x8b", "GZIP"),
    (_RIFF_MAGIC, "RIFF"),
)

WAV_INFO_PREFIX = "__AEGIS_WAV_INFO__:"
WAV_METADATA_PREFIX = "__AEGIS_WAV_METADATA__:"
WAV_WARNING_PREFIX = "__AEGIS_WAV_WARNING__:"
WAV_CHUNK_PREFIX = "__AEGIS_WAV_CHUNK__:"
WAV_TRAILING_PREFIX = "__AEGIS_WAV_TRAILING__:"
WAV_FLAG_PREFIX = "__AEGIS_WAV_FLAG__:"

_EMPTY_RESULT = WavStaticResult(
    valid_header=False,
    riff_declared_size=None,
    actual_file_size=0,
    audio_format=None,
    format_name=None,
    channel_count=None,
    sample_rate=None,
    byte_rate=None,
    block_align=None,
    bits_per_sample=None,
    duration_seconds=None,
    chunks=(),
    metadata_items=(),
    warnings=(),
    flag_candidates=(),
    trailing_data=None,
    truncated=False,
)


def wav_static_summary_strings(result: WavStaticResult) -> list[str]:
    """WavStaticResultを予約prefix付きの安全なsummary文字列へ変換する。"""
    if not result.valid_header:
        return []
    values: list[str] = []
    if result.format_name is not None or result.channel_count is not None:
        duration = (
            f"{result.duration_seconds:.2f}"
            if result.duration_seconds is not None
            else "unknown"
        )
        values.append(
            f"{WAV_INFO_PREFIX}format={result.format_name or result.audio_format} "
            f"channels={result.channel_count} rate={result.sample_rate} "
            f"bits={result.bits_per_sample} duration={duration}"
        )
    for item in result.metadata_items:
        values.append(f"{WAV_METADATA_PREFIX}{item.key}={item.value_preview}")
    for chunk in result.chunks:
        if not chunk.known:
            values.append(f"{WAV_CHUNK_PREFIX}id={chunk.chunk_id} size={chunk.declared_size}")
    for warning in result.warnings:
        values.append(f"{WAV_WARNING_PREFIX}{warning}")
    if result.trailing_data is not None:
        magic = result.trailing_data.detected_magic or "unknown"
        values.append(
            f"{WAV_TRAILING_PREFIX}size={result.trailing_data.size} magic={magic}"
        )
    for flag in result.flag_candidates:
        values.append(f"{WAV_FLAG_PREFIX}candidate={flag}")
    return values


class WavStaticAnalyzer:
    """WAV/RIFFの構造・fmt・metadata・未知chunk・末尾データを安全に静的解析する。"""

    def __init__(self, flag_extractor: FlagExtractor | None = None) -> None:
        self._flag_extractor = flag_extractor or FlagExtractor()

    def analyze(self, content: bytes) -> WavStaticResult:
        if not (
            content.startswith(_RIFF_MAGIC)
            and len(content) >= 12
            and content[8:12] == _WAVE_MAGIC
        ):
            return _EMPTY_RESULT
        if len(content) > _MAX_FILE_SIZE:
            return WavStaticResult(
                valid_header=True,
                riff_declared_size=None,
                actual_file_size=len(content),
                audio_format=None,
                format_name=None,
                channel_count=None,
                sample_rate=None,
                byte_rate=None,
                block_align=None,
                bits_per_sample=None,
                duration_seconds=None,
                chunks=(),
                metadata_items=(),
                warnings=("ファイルサイズが上限（50MB）を超えているため解析を中止しました。",),
                flag_candidates=(),
                trailing_data=None,
                truncated=True,
            )

        riff_declared_size = struct.unpack_from("<I", content, 4)[0]

        warnings: list[str] = []
        chunks: list[WavChunkItem] = []
        metadata_items: list[WavMetadataItem] = []

        if riff_declared_size != len(content) - 8:
            warnings.append("RIFF宣言サイズがファイルサイズと一致しません。")

        fields = {
            "audio_format": None,
            "format_name": None,
            "channel_count": None,
            "sample_rate": None,
            "byte_rate": None,
            "block_align": None,
            "bits_per_sample": None,
        }
        fmt_count = 0
        data_count = 0
        total_data_bytes = 0

        offset, truncated = self._walk_chunks(
            content, warnings, chunks, metadata_items, fields
        )

        for chunk in chunks:
            if chunk.chunk_id == "fmt ":
                fmt_count += 1
            if chunk.chunk_id == "data":
                data_count += 1
                total_data_bytes += chunk.actual_size

        if fmt_count == 0:
            warnings.append("fmtチャンクが見つかりません。")
        elif fmt_count > 1:
            warnings.append("fmtチャンクが複数回出現しています。")
        if data_count == 0:
            warnings.append("dataチャンクが見つかりません。")
        elif data_count > 1:
            warnings.append("dataチャンクが複数回出現しています。")

        duration_seconds = None
        if fields["byte_rate"] and total_data_bytes > 0:
            duration_seconds = total_data_bytes / fields["byte_rate"]

        trailing_data = None
        if offset < len(content):
            trailing_data = self._analyze_trailing(content, offset)

        flag_candidates: list[str] = []
        seen_flags: set[str] = set()
        for item in metadata_items:
            self._merge_flags(flag_candidates, seen_flags, item.flag_candidates)
        for chunk in chunks:
            if not chunk.known:
                self._merge_flags(
                    flag_candidates,
                    seen_flags,
                    self._flag_extractor.extract_all(chunk.detail),
                )
        if trailing_data is not None:
            self._merge_flags(
                flag_candidates, seen_flags, trailing_data.flag_candidates
            )

        return WavStaticResult(
            valid_header=True,
            riff_declared_size=riff_declared_size,
            actual_file_size=len(content),
            audio_format=fields["audio_format"],
            format_name=fields["format_name"],
            channel_count=fields["channel_count"],
            sample_rate=fields["sample_rate"],
            byte_rate=fields["byte_rate"],
            block_align=fields["block_align"],
            bits_per_sample=fields["bits_per_sample"],
            duration_seconds=duration_seconds,
            chunks=tuple(chunks),
            metadata_items=tuple(metadata_items),
            warnings=tuple(warnings),
            flag_candidates=tuple(flag_candidates[:_MAX_FLAGS]),
            trailing_data=trailing_data,
            truncated=truncated,
        )

    # -- chunk walking --------------------------------------------------------

    def _walk_chunks(
        self,
        content: bytes,
        warnings: list[str],
        chunks: list[WavChunkItem],
        metadata_items: list[WavMetadataItem],
        fields: dict[str, object],
    ) -> tuple[int, bool]:
        offset = 12
        truncated = False

        while offset + 8 <= len(content):
            if len(chunks) >= _MAX_CHUNKS:
                warnings.append("chunk数が上限を超えたため解析を打ち切りました。")
                truncated = True
                break

            chunk_id_bytes = content[offset : offset + 4]
            if not all(0x20 <= byte <= 0x7E for byte in chunk_id_bytes):
                # 印字可能ASCIIでないchunk IDはRIFF構造の終端とみなし、
                # 残りをtrailing dataとして扱う（末尾追加データの誤解析防止）。
                break
            chunk_id = chunk_id_bytes.decode("latin-1")
            declared_size = struct.unpack_from("<I", content, offset + 4)[0]
            data_start = offset + 8
            data_end = data_start + declared_size

            if data_end > len(content):
                actual_size = max(0, len(content) - data_start)
                warnings.append(
                    f"chunk「{chunk_id}」(offset 0x{offset:X}) が"
                    "ファイル範囲外または切り詰められています。"
                )
                chunks.append(
                    WavChunkItem(
                        chunk_id=chunk_id,
                        offset=offset,
                        declared_size=declared_size,
                        actual_size=actual_size,
                        known=chunk_id in _KNOWN_CHUNKS,
                        detail=f"{actual_size} bytes (truncated)",
                        truncated=True,
                    )
                )
                truncated = True
                break

            payload = content[data_start:data_end]
            known = chunk_id in _KNOWN_CHUNKS
            detail = self._build_detail(chunk_id, payload, offset, metadata_items, fields, warnings)

            chunks.append(
                WavChunkItem(
                    chunk_id=chunk_id,
                    offset=offset,
                    declared_size=declared_size,
                    actual_size=len(payload),
                    known=known,
                    detail=detail,
                    truncated=False,
                )
            )

            next_offset = data_end
            if declared_size % 2 == 1:
                if next_offset < len(content):
                    next_offset += 1
                else:
                    warnings.append(
                        f"chunk「{chunk_id}」のpaddingバイトが欠落している可能性があります。"
                    )
            offset = next_offset

        return offset, truncated

    def _build_detail(
        self,
        chunk_id: str,
        payload: bytes,
        offset: int,
        metadata_items: list[WavMetadataItem],
        fields: dict[str, object],
        warnings: list[str],
    ) -> str:
        if chunk_id == "fmt ":
            return self._handle_fmt(payload, fields, warnings)
        if chunk_id == "data":
            return f"{len(payload)} bytes (audio data, not stored)"
        if chunk_id == "LIST":
            return self._handle_list(payload, offset, metadata_items, warnings)
        if chunk_id == "bext":
            return self._handle_bext(payload, offset, metadata_items)
        if chunk_id == "iXML":
            return self._handle_ixml(payload, offset, metadata_items)
        if chunk_id in ("id3 ", "ID3 "):
            return self._handle_id3(payload, offset, metadata_items)
        if chunk_id == "DISP":
            return self._handle_disp(payload, offset, metadata_items)
        if chunk_id == "fact" and len(payload) >= 4:
            sample_length = struct.unpack_from("<I", payload, 0)[0]
            return f"sample_length={sample_length}"
        if chunk_id == "cue " and len(payload) >= 4:
            count = struct.unpack_from("<I", payload, 0)[0]
            return f"cue_point_count={count}"
        if chunk_id == "smpl" and len(payload) >= 36:
            loop_count = struct.unpack_from("<I", payload, 28)[0]
            sampler_data_size = struct.unpack_from("<I", payload, 32)[0]
            return f"loop_count={loop_count} sampler_data_size={sampler_data_size}"
        if chunk_id in _UNKNOWN_SCAN_CHUNKS or chunk_id not in _KNOWN_CHUNKS:
            return self._scan_unknown(payload)
        return f"{len(payload)} bytes"

    # -- fmt --------------------------------------------------------------------

    def _handle_fmt(
        self, payload: bytes, fields: dict[str, object], warnings: list[str]
    ) -> str:
        if fields["audio_format"] is not None:
            return f"{len(payload)} bytes (duplicate fmt)"
        if len(payload) < 16:
            warnings.append("fmtチャンクの長さが16バイト未満です。")
            return f"{len(payload)} bytes (invalid fmt length)"

        audio_format, channels, sample_rate, byte_rate, block_align, bits = (
            struct.unpack_from("<HHIIHH", payload, 0)
        )
        fields["audio_format"] = audio_format
        fields["format_name"] = _FORMAT_NAMES.get(
            audio_format, f"Unknown(0x{audio_format:04X})"
        )
        fields["channel_count"] = channels
        fields["sample_rate"] = sample_rate
        fields["byte_rate"] = byte_rate
        fields["block_align"] = block_align
        fields["bits_per_sample"] = bits

        if channels == 0:
            warnings.append("channel_countが0です。")
        if sample_rate == 0:
            warnings.append("sample_rateが0です。")
        if byte_rate == 0:
            warnings.append("byte_rateが0です。")
        if block_align == 0:
            warnings.append("block_alignが0です。")
        if bits == 0:
            warnings.append("bits_per_sampleが0です。")

        if audio_format == 1 and channels and bits:
            expected_block_align = channels * bits // 8
            if block_align != expected_block_align:
                warnings.append("block_alignの整合性が不自然です。")
            expected_byte_rate = sample_rate * expected_block_align
            if byte_rate != expected_byte_rate:
                warnings.append("byte_rateの整合性が不自然です。")

        extension_size = None
        if len(payload) >= 18:
            extension_size = struct.unpack_from("<H", payload, 16)[0]

        return (
            f"audio_format={audio_format} channels={channels} "
            f"sample_rate={sample_rate} byte_rate={byte_rate} "
            f"block_align={block_align} bits_per_sample={bits} "
            f"extension_size={extension_size}"
        )

    # -- LIST/INFO --------------------------------------------------------------

    def _handle_list(
        self,
        payload: bytes,
        chunk_offset: int,
        metadata_items: list[WavMetadataItem],
        warnings: list[str],
    ) -> str:
        if len(payload) < 4 or payload[:4] != b"INFO":
            return f"{len(payload)} bytes (list_type={payload[:4]!r})"

        sub_offset = 4
        base_offset = chunk_offset + 8 + 4
        count = 0
        while sub_offset + 8 <= len(payload):
            if len(metadata_items) >= _MAX_METADATA_ITEMS:
                warnings.append("metadata件数が上限を超えたため打ち切りました。")
                break
            sub_id = payload[sub_offset : sub_offset + 4].decode("latin-1")
            sub_size = struct.unpack_from("<I", payload, sub_offset + 4)[0]
            sub_data_start = sub_offset + 8
            sub_data_end = sub_data_start + sub_size
            if sub_data_end > len(payload):
                warnings.append("LIST内のsub-chunkがLISTチャンクの範囲外です。")
                break
            sub_payload = payload[sub_data_start:sub_data_end]
            if sub_id in _INFO_KEYS:
                item = self._build_metadata_item(
                    "LIST/INFO",
                    sub_id,
                    self._decode_text(sub_payload),
                    base_offset + sub_offset,
                )
                metadata_items.append(item)
                count += 1
            next_offset = sub_data_end
            if sub_size % 2 == 1 and next_offset < len(payload):
                next_offset += 1
            sub_offset = next_offset
        return f"INFO subchunks={count}"

    # -- bext ---------------------------------------------------------------

    def _handle_bext(
        self,
        payload: bytes,
        chunk_offset: int,
        metadata_items: list[WavMetadataItem],
    ) -> str:
        base_offset = chunk_offset + 8
        fields_found = 0

        def add(key: str, start: int, length: int) -> None:
            nonlocal fields_found
            if len(payload) >= start + length:
                value = self._decode_text(payload[start : start + length])
                if value:
                    metadata_items.append(
                        self._build_metadata_item(
                            "bext", key, value, base_offset + start
                        )
                    )
                    fields_found += 1

        add("description", 0, 256)
        add("originator", 256, 32)
        add("originator_reference", 288, 32)
        add("origination_date", 320, 10)
        add("origination_time", 330, 8)
        if len(payload) >= 346:
            version = struct.unpack_from("<H", payload, 344)[0]
            metadata_items.append(
                self._build_metadata_item(
                    "bext", "version", str(version), base_offset + 344
                )
            )
            fields_found += 1
        if len(payload) > 602:
            history = self._decode_text(payload[602:])
            if history:
                metadata_items.append(
                    self._build_metadata_item(
                        "bext", "coding_history", history, base_offset + 602
                    )
                )
                fields_found += 1
        return f"{len(payload)} bytes ({fields_found} fields)"

    # -- iXML -----------------------------------------------------------------

    def _handle_ixml(
        self,
        payload: bytes,
        chunk_offset: int,
        metadata_items: list[WavMetadataItem],
    ) -> str:
        limited = payload[:_MAX_IXML_BYTES]
        truncated = len(payload) > _MAX_IXML_BYTES
        text = limited.decode("utf-8", errors="replace")
        base_offset = chunk_offset + 8
        found = 0
        for tag in _IXML_TAGS:
            match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
            if match is None:
                continue
            value = " ".join(match.group(1).split())
            if not value:
                continue
            metadata_items.append(
                self._build_metadata_item(
                    "iXML", tag, value, base_offset + match.start(), truncated=truncated
                )
            )
            found += 1
        return f"{len(payload)} bytes ({found} fields, truncated={truncated})"

    # -- ID3 --------------------------------------------------------------------

    def _handle_id3(
        self,
        payload: bytes,
        chunk_offset: int,
        metadata_items: list[WavMetadataItem],
    ) -> str:
        if len(payload) < 10 or payload[:3] != b"ID3":
            return f"{len(payload)} bytes (invalid ID3 header)"
        version = f"2.{payload[3]}.{payload[4]}"
        flags = payload[5]
        declared_size = self._syncsafe(payload[6:10])
        base_offset = chunk_offset + 8

        limited = payload[10 : 10 + min(declared_size, _MAX_ID3_BYTES)]
        found = 0
        frame_offset = 0
        while frame_offset + 10 <= len(limited) and len(metadata_items) < _MAX_METADATA_ITEMS:
            frame_id = limited[frame_offset : frame_offset + 4]
            if not frame_id.isascii() or not frame_id.decode("ascii").isalnum():
                break
            frame_id_text = frame_id.decode("ascii")
            frame_size = self._syncsafe(limited[frame_offset + 4 : frame_offset + 8])
            frame_data_start = frame_offset + 10
            frame_data_end = frame_data_start + frame_size
            if frame_size <= 0 or frame_data_end > len(limited):
                break
            if frame_id_text in _ID3_TEXT_FRAMES:
                frame_data = limited[frame_data_start:frame_data_end]
                text_value = self._decode_text(frame_data.lstrip(b"\x00\x01\x02\x03"))
                if text_value:
                    metadata_items.append(
                        self._build_metadata_item(
                            "ID3",
                            frame_id_text,
                            text_value,
                            base_offset + 10 + frame_data_start,
                        )
                    )
                    found += 1
            frame_offset = frame_data_end

        return (
            f"ID3v{version} flags=0x{flags:02X} declared_size={declared_size} "
            f"text_frames={found}"
        )

    @staticmethod
    def _syncsafe(data: bytes) -> int:
        if len(data) < 4:
            return 0
        return (
            ((data[0] & 0x7F) << 21)
            | ((data[1] & 0x7F) << 14)
            | ((data[2] & 0x7F) << 7)
            | (data[3] & 0x7F)
        )

    # -- DISP -------------------------------------------------------------------

    def _handle_disp(
        self,
        payload: bytes,
        chunk_offset: int,
        metadata_items: list[WavMetadataItem],
    ) -> str:
        if len(payload) < 4:
            return f"{len(payload)} bytes"
        disp_type = struct.unpack_from("<I", payload, 0)[0]
        text = self._decode_text(payload[4:])
        if disp_type == 1 and text:
            metadata_items.append(
                self._build_metadata_item(
                    "DISP", "DISP", text, chunk_offset + 8 + 4
                )
            )
        return f"type={disp_type} {len(payload)} bytes"

    # -- unknown / JUNK / PAD -----------------------------------------------------

    def _scan_unknown(self, payload: bytes) -> str:
        held = payload[:_MAX_UNKNOWN_SCAN_BYTES]
        magic = self._detect_magic(held)
        strings = self._extract_ascii_strings(held)
        detail = f"{len(payload)} bytes"
        if magic:
            detail += f" magic={magic}"
        flags: list[str] = []
        seen: set[str] = set()
        for value in strings:
            self._merge_flags(flags, seen, self._flag_extractor.extract_all(value))
        if flags:
            detail += " flag_candidates=" + ",".join(flags[:5])
        return detail

    # -- metadata helpers ---------------------------------------------------

    def _build_metadata_item(
        self,
        source: str,
        key: str,
        value: str,
        offset: int,
        *,
        truncated: bool = False,
    ) -> WavMetadataItem:
        item_truncated = truncated or len(value) > _MAX_VALUE_LENGTH
        limited_value = value[:_MAX_VALUE_LENGTH]
        preview = limited_value[:_MAX_PREVIEW]
        if len(limited_value) > _MAX_PREVIEW:
            item_truncated = True
        label = _INFO_KEYS.get(key, key)
        important = self._is_important(label) or self._is_important(key)
        flags = self._flag_extractor.extract_all(preview)
        return WavMetadataItem(
            source=source,
            key=key,
            value_preview=self._sanitize_preview(preview),
            offset=offset,
            important=important,
            flag_candidates=tuple(flags[:_MAX_FLAGS]),
            truncated=item_truncated,
        )

    @staticmethod
    def _is_important(label: str) -> bool:
        lowered = label.lower()
        return any(word in lowered for word in _IMPORTANT_KEYWORDS)

    @staticmethod
    def _decode_text(raw: bytes) -> str:
        cleaned = raw.split(b"\x00", 1)[0]
        try:
            return cleaned.decode("utf-8").strip()
        except UnicodeDecodeError:
            return cleaned.decode("latin-1", errors="replace").strip()

    # -- trailing data ----------------------------------------------------------

    def _analyze_trailing(
        self, content: bytes, start_offset: int
    ) -> WavTrailingDataResult | None:
        remaining = content[start_offset:]
        if not remaining:
            return None
        size = len(remaining)
        held = remaining[:_MAX_TRAILING_BYTES]
        truncated = size > _MAX_TRAILING_BYTES
        preview = self._sanitize_preview(held[:_MAX_PREVIEW].decode("latin-1"))
        magic = self._detect_magic(held)
        strings = self._extract_ascii_strings(held)

        flags: list[str] = []
        seen: set[str] = set()
        self._merge_flags(flags, seen, self._flag_extractor.extract_all(preview))
        for value in strings:
            self._merge_flags(flags, seen, self._flag_extractor.extract_all(value))

        return WavTrailingDataResult(
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

    # -- shared helpers -----------------------------------------------------

    @staticmethod
    def _sanitize_preview(value: str) -> str:
        return "".join(
            ch if (0x20 <= ord(ch) <= 0x7E or ch in "\n\r\t") else "."
            for ch in value
        )

    @staticmethod
    def _merge_flags(
        target: list[str], seen: set[str], candidates: tuple[str, ...] | list[str]
    ) -> None:
        for flag in candidates:
            if flag not in seen and len(target) < _MAX_FLAGS:
                seen.add(flag)
                target.append(flag)
