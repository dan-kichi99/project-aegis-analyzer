import re
import struct

from app.file.jpeg_metadata_result import (
    JpegMetadataResult,
    JpegSegmentItem,
    JpegTrailingDataResult,
)
from app.judge.flag_extractor import FlagExtractor

_SOI = b"\xff\xd8"

_MAX_FILE_SIZE = 50_000_000
_MAX_SEGMENTS = 100
_MAX_COMMENTS = 100
_MAX_PREVIEW = 500
_MAX_APP_SEGMENT_LENGTH = 60_000
_MAX_TRAILING_BYTES = 1_000_000
_MAX_STRINGS = 100
_MAX_FLAGS = 100
_MIN_STRING_LENGTH = 4
_MAX_STRING_LENGTH = 300

_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)

_TIFF_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}
_TAG_MAKE = 0x010F
_TAG_MODEL = 0x0110
_TAG_SOFTWARE = 0x0131
_TAG_ARTIST = 0x013B
_TAG_COPYRIGHT = 0x8298
_TAG_DATETIME = 0x0132
_TAG_ORIENTATION = 0x0112
_TAG_EXIF_IFD = 0x8769
_TAG_GPS_IFD = 0x8825
_TAG_DATETIME_ORIGINAL = 0x9003

_XMP_NAMESPACE = b"http://ns.adobe.com/xap/1.0/\x00"

_MAGIC_SIGNATURES = (
    (b"PK\x03\x04", "ZIP"),
    (b"PK\x05\x06", "ZIP"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"%PDF-", "PDF"),
    (b"\x1f\x8b", "GZIP"),
    (b"\x7fELF", "ELF"),
    (b"MZ", "PE"),
)

JPEG_INFO_PREFIX = "__AEGIS_JPEG_INFO__:"
JPEG_WARNING_PREFIX = "__AEGIS_JPEG_WARNING__:"
JPEG_COMMENT_PREFIX = "__AEGIS_JPEG_COMMENT__:"
JPEG_FLAG_PREFIX = "__AEGIS_JPEG_FLAG__:"
JPEG_TRAILING_PREFIX = "__AEGIS_JPEG_TRAILING__:"

_EMPTY_RESULT = JpegMetadataResult(
    valid_header=False,
    width=None,
    height=None,
    color_components=None,
    jpeg_version=None,
    has_jfif=False,
    has_exif=False,
    has_icc_profile=False,
    has_adobe=False,
    has_xmp=False,
    has_gps=False,
    make=None,
    model=None,
    software=None,
    artist=None,
    copyright=None,
    datetime=None,
    orientation=None,
    xmp_creator=None,
    xmp_description=None,
    xmp_title=None,
    xmp_keywords=None,
    segments=(),
    comments=(),
    warnings=(),
    flag_candidates=(),
    trailing_data=None,
    truncated=False,
)


def jpeg_metadata_summary_strings(result: JpegMetadataResult) -> list[str]:
    """JpegMetadataResultを予約prefix付きの安全なsummary文字列へ変換する。"""
    if not result.valid_header:
        return []
    values: list[str] = []
    if result.width is not None and result.height is not None:
        values.append(
            f"{JPEG_INFO_PREFIX}width={result.width} height={result.height} "
            f"color_components={result.color_components}"
        )
    for label, value in (
        ("Make", result.make),
        ("Model", result.model),
        ("Software", result.software),
        ("Artist", result.artist),
        ("Copyright", result.copyright),
        ("DateTime", result.datetime),
        ("Orientation", result.orientation),
        ("XMP_Creator", result.xmp_creator),
        ("XMP_Description", result.xmp_description),
        ("XMP_Title", result.xmp_title),
        ("XMP_Keywords", result.xmp_keywords),
    ):
        if value is not None:
            values.append(f"{JPEG_INFO_PREFIX}{label}={value}")
    for comment in result.comments:
        values.append(f"{JPEG_COMMENT_PREFIX}{comment}")
    for warning in result.warnings:
        values.append(f"{JPEG_WARNING_PREFIX}{warning}")
    if result.trailing_data is not None:
        magic = result.trailing_data.detected_magic or "unknown"
        values.append(
            f"{JPEG_TRAILING_PREFIX}size={result.trailing_data.size} magic={magic}"
        )
    for flag in result.flag_candidates:
        values.append(f"{JPEG_FLAG_PREFIX}candidate={flag}")
    return values


class JpegMetadataAnalyzer:
    """JPEGの構造・APPセグメント・Exif・XMP・Comment・末尾データを安全に静的解析する。"""

    def __init__(self, flag_extractor: FlagExtractor | None = None) -> None:
        self._flag_extractor = flag_extractor or FlagExtractor()

    def analyze(self, content: bytes) -> JpegMetadataResult:
        if not content.startswith(_SOI):
            return _EMPTY_RESULT
        if len(content) > _MAX_FILE_SIZE:
            return self._oversized_result()

        warnings: list[str] = []
        segments: list[JpegSegmentItem] = []
        comments: list[str] = []
        fields: dict[str, object] = {
            "width": None,
            "height": None,
            "color_components": None,
            "jpeg_version": None,
            "has_jfif": False,
            "has_exif": False,
            "has_icc_profile": False,
            "has_adobe": False,
            "has_xmp": False,
            "has_gps": False,
            "make": None,
            "model": None,
            "software": None,
            "artist": None,
            "copyright": None,
            "datetime": None,
            "orientation": None,
            "xmp_creator": None,
            "xmp_description": None,
            "xmp_title": None,
            "xmp_keywords": None,
        }

        offset, truncated, sos_end = self._walk_metadata_segments(
            content, warnings, segments, comments, fields
        )

        eoi_offset: int | None
        if sos_end is None:
            eoi_offset = offset if offset <= len(content) else None
        else:
            eoi_offset = self._find_scan_eoi(content, sos_end)
            if eoi_offset is None:
                warnings.append("EOI（FFD9）が見つかりません。")

        trailing_data = None
        if eoi_offset is not None and eoi_offset < len(content):
            trailing_data = self._analyze_trailing(content, eoi_offset)

        flag_candidates: list[str] = []
        seen_flags: set[str] = set()
        for comment in comments:
            self._merge_flags(
                flag_candidates, seen_flags, self._flag_extractor.extract_all(comment)
            )
        for value in (
            fields["make"],
            fields["model"],
            fields["software"],
            fields["artist"],
            fields["copyright"],
            fields["datetime"],
            fields["xmp_creator"],
            fields["xmp_description"],
            fields["xmp_title"],
            fields["xmp_keywords"],
        ):
            if value is not None:
                self._merge_flags(
                    flag_candidates, seen_flags, self._flag_extractor.extract_all(value)
                )
        if trailing_data is not None:
            self._merge_flags(
                flag_candidates, seen_flags, trailing_data.flag_candidates
            )

        return JpegMetadataResult(
            valid_header=True,
            width=fields["width"],
            height=fields["height"],
            color_components=fields["color_components"],
            jpeg_version=fields["jpeg_version"],
            has_jfif=fields["has_jfif"],
            has_exif=fields["has_exif"],
            has_icc_profile=fields["has_icc_profile"],
            has_adobe=fields["has_adobe"],
            has_xmp=fields["has_xmp"],
            has_gps=fields["has_gps"],
            make=fields["make"],
            model=fields["model"],
            software=fields["software"],
            artist=fields["artist"],
            copyright=fields["copyright"],
            datetime=fields["datetime"],
            orientation=fields["orientation"],
            xmp_creator=fields["xmp_creator"],
            xmp_description=fields["xmp_description"],
            xmp_title=fields["xmp_title"],
            xmp_keywords=fields["xmp_keywords"],
            segments=tuple(segments),
            comments=tuple(comments),
            warnings=tuple(warnings),
            flag_candidates=tuple(flag_candidates[:_MAX_FLAGS]),
            trailing_data=trailing_data,
            truncated=truncated,
        )

    @staticmethod
    def _oversized_result() -> JpegMetadataResult:
        return JpegMetadataResult(
            valid_header=True,
            width=None,
            height=None,
            color_components=None,
            jpeg_version=None,
            has_jfif=False,
            has_exif=False,
            has_icc_profile=False,
            has_adobe=False,
            has_xmp=False,
            has_gps=False,
            make=None,
            model=None,
            software=None,
            artist=None,
            copyright=None,
            datetime=None,
            orientation=None,
            xmp_creator=None,
            xmp_description=None,
            xmp_title=None,
            xmp_keywords=None,
            segments=(),
            comments=(),
            warnings=("ファイルサイズが上限（50MB）を超えているため解析を中止しました。",),
            flag_candidates=(),
            trailing_data=None,
            truncated=True,
        )

    # -- marker walking -------------------------------------------------------

    def _walk_metadata_segments(
        self,
        content: bytes,
        warnings: list[str],
        segments: list[JpegSegmentItem],
        comments: list[str],
        fields: dict[str, object],
    ) -> tuple[int, bool, int | None]:
        offset = 2
        truncated = False
        sos_end: int | None = None

        while offset < len(content):
            if content[offset] != 0xFF:
                warnings.append("マーカーが不正なため解析を打ち切りました。")
                truncated = True
                break
            marker_pos = offset
            while offset < len(content) and content[offset] == 0xFF:
                offset += 1
            if offset >= len(content):
                warnings.append("ファイルがマーカーの途中で終了しています。")
                truncated = True
                break
            marker = content[offset]
            offset += 1

            if marker == 0xD9:
                break
            if marker == 0x01 or 0xD0 <= marker <= 0xD7:
                continue

            if offset + 2 > len(content):
                warnings.append("セグメント長が読み取れないため解析を打ち切りました。")
                truncated = True
                break
            length = struct.unpack_from(">H", content, offset)[0]
            if length < 2:
                warnings.append("セグメント長が不正です。")
                truncated = True
                break
            if length > _MAX_APP_SEGMENT_LENGTH:
                warnings.append(
                    f"異常に大きなAPPセグメントを検出しました（marker=0xFF{marker:02X}）。"
                )
                truncated = True
                break
            data_start = offset + 2
            segment_end = offset + length
            if segment_end > len(content):
                warnings.append("セグメントがファイル範囲外または切り詰められています。")
                truncated = True
                break

            payload = content[data_start:segment_end]
            self._handle_segment(
                marker, marker_pos, length, payload, segments, comments, fields
            )

            offset = segment_end
            if marker == 0xDA:
                sos_end = offset
                break

        return offset, truncated, sos_end

    def _handle_segment(
        self,
        marker: int,
        marker_pos: int,
        length: int,
        payload: bytes,
        segments: list[JpegSegmentItem],
        comments: list[str],
        fields: dict[str, object],
    ) -> None:
        if 0xE0 <= marker <= 0xEF:
            name = f"APP{marker - 0xE0}"
            if len(segments) < _MAX_SEGMENTS:
                preview = self._sanitize_preview(
                    payload[:_MAX_PREVIEW].decode("latin-1")
                )
                segments.append(JpegSegmentItem(name, marker_pos, length, preview))
            self._handle_app_segment(marker - 0xE0, payload, fields)
        elif marker == 0xFE:
            if len(segments) < _MAX_SEGMENTS:
                preview = self._sanitize_preview(
                    payload[:_MAX_PREVIEW].decode("latin-1")
                )
                segments.append(JpegSegmentItem("COM", marker_pos, length, preview))
            if len(comments) < _MAX_COMMENTS:
                comments.append(
                    self._sanitize_preview(payload.decode("latin-1")[:_MAX_PREVIEW])
                )
        elif marker in _SOF_MARKERS:
            if len(payload) >= 6 and fields["width"] is None:
                _precision, height, width = struct.unpack_from(">BHH", payload, 0)
                fields["width"] = width
                fields["height"] = height
                fields["color_components"] = payload[5]

    def _handle_app_segment(
        self, app_index: int, payload: bytes, fields: dict[str, object]
    ) -> None:
        if app_index == 0 and payload.startswith(b"JFIF\x00"):
            fields["has_jfif"] = True
            if len(payload) >= 7:
                fields["jpeg_version"] = f"{payload[5]}.{payload[6]:02d}"
        elif app_index == 1 and payload.startswith(b"Exif\x00\x00"):
            fields["has_exif"] = True
            exif = self._parse_exif(payload[6:])
            for key in (
                "make",
                "model",
                "software",
                "artist",
                "copyright",
                "datetime",
                "orientation",
            ):
                if fields.get(key) is None and exif.get(key) is not None:
                    fields[key] = exif[key]
            if exif.get("has_gps"):
                fields["has_gps"] = True
        elif app_index == 1 and payload.startswith(_XMP_NAMESPACE):
            fields["has_xmp"] = True
            xmp_text = payload[len(_XMP_NAMESPACE) :].decode("utf-8", errors="replace")
            fields["xmp_creator"] = self._extract_xmp_field(xmp_text, "dc:creator")
            fields["xmp_description"] = self._extract_xmp_field(
                xmp_text, "dc:description"
            )
            fields["xmp_title"] = self._extract_xmp_field(xmp_text, "dc:title")
            fields["xmp_keywords"] = self._extract_xmp_field(
                xmp_text, "dc:subject"
            ) or self._extract_xmp_field(xmp_text, "pdf:Keywords")
        elif app_index == 2 and payload.startswith(b"ICC_PROFILE\x00"):
            fields["has_icc_profile"] = True
        elif app_index == 14 and payload.startswith(b"Adobe"):
            fields["has_adobe"] = True

    # -- Exif / TIFF ------------------------------------------------------------

    def _parse_exif(self, tiff: bytes) -> dict[str, object]:
        info: dict[str, object] = {
            "make": None,
            "model": None,
            "software": None,
            "artist": None,
            "copyright": None,
            "datetime": None,
            "orientation": None,
            "has_gps": False,
        }
        if len(tiff) < 8 or tiff[:2] not in (b"II", b"MM"):
            return info
        endian = "<" if tiff[:2] == b"II" else ">"
        try:
            if struct.unpack_from(f"{endian}H", tiff, 2)[0] != 42:
                return info
            first_ifd = struct.unpack_from(f"{endian}I", tiff, 4)[0]
        except struct.error:
            return info

        entries = self._read_ifd(tiff, first_ifd, endian)
        exif_ifd_offset: int | None = None
        for tag, value_type, count, entry_start in entries:
            if tag == _TAG_MAKE:
                info["make"] = self._decode_ascii(tiff, entry_start, value_type, count, endian)
            elif tag == _TAG_MODEL:
                info["model"] = self._decode_ascii(tiff, entry_start, value_type, count, endian)
            elif tag == _TAG_SOFTWARE:
                info["software"] = self._decode_ascii(tiff, entry_start, value_type, count, endian)
            elif tag == _TAG_ARTIST:
                info["artist"] = self._decode_ascii(tiff, entry_start, value_type, count, endian)
            elif tag == _TAG_COPYRIGHT:
                info["copyright"] = self._decode_ascii(tiff, entry_start, value_type, count, endian)
            elif tag == _TAG_DATETIME:
                info["datetime"] = self._decode_ascii(tiff, entry_start, value_type, count, endian)
            elif tag == _TAG_ORIENTATION:
                info["orientation"] = self._decode_int(tiff, entry_start, value_type, count, endian)
            elif tag == _TAG_GPS_IFD:
                info["has_gps"] = True
            elif tag == _TAG_EXIF_IFD:
                exif_ifd_offset = self._decode_int(tiff, entry_start, 4, 1, endian)

        if exif_ifd_offset is not None and 0 <= exif_ifd_offset < len(tiff):
            for tag, value_type, count, entry_start in self._read_ifd(
                tiff, exif_ifd_offset, endian
            ):
                if tag == _TAG_DATETIME_ORIGINAL and info["datetime"] is None:
                    info["datetime"] = self._decode_ascii(
                        tiff, entry_start, value_type, count, endian
                    )
                elif tag == _TAG_GPS_IFD:
                    info["has_gps"] = True
        return info

    @staticmethod
    def _read_ifd(
        tiff: bytes, offset: int, endian: str
    ) -> list[tuple[int, int, int, int]]:
        entries: list[tuple[int, int, int, int]] = []
        if offset < 0 or offset + 2 > len(tiff):
            return entries
        try:
            count = struct.unpack_from(f"{endian}H", tiff, offset)[0]
        except struct.error:
            return entries
        if count > 200 or offset + 2 + count * 12 > len(tiff):
            return entries
        for index in range(count):
            start = offset + 2 + index * 12
            try:
                tag, value_type = struct.unpack_from(f"{endian}HH", tiff, start)
                value_count = struct.unpack_from(f"{endian}I", tiff, start + 4)[0]
            except struct.error:
                continue
            entries.append((tag, value_type, value_count, start))
        return entries

    @staticmethod
    def _tag_value_bytes(
        tiff: bytes, entry_start: int, value_type: int, count: int, endian: str
    ) -> bytes | None:
        unit_size = _TIFF_TYPE_SIZES.get(value_type)
        if unit_size is None or count < 0 or count > 100_000:
            return None
        size = unit_size * count
        if size <= 4:
            return tiff[entry_start + 8 : entry_start + 8 + size]
        if size > 1_000_000:
            return None
        try:
            value_offset = struct.unpack_from(f"{endian}I", tiff, entry_start + 8)[0]
        except struct.error:
            return None
        if value_offset < 0 or value_offset + size > len(tiff):
            return None
        return tiff[value_offset : value_offset + size]

    def _decode_ascii(
        self, tiff: bytes, entry_start: int, value_type: int, count: int, endian: str
    ) -> str | None:
        if value_type != 2:
            return None
        raw = self._tag_value_bytes(tiff, entry_start, value_type, count, endian)
        if raw is None:
            return None
        value = raw.rstrip(b"\x00").decode("ascii", errors="replace").strip()
        return value or None

    def _decode_int(
        self, tiff: bytes, entry_start: int, value_type: int, count: int, endian: str
    ) -> int | None:
        raw = self._tag_value_bytes(tiff, entry_start, value_type, count, endian)
        if raw is None:
            return None
        if value_type == 3 and len(raw) >= 2:
            return struct.unpack_from(f"{endian}H", raw, 0)[0]
        if value_type == 4 and len(raw) >= 4:
            return struct.unpack_from(f"{endian}I", raw, 0)[0]
        return None

    # -- XMP ------------------------------------------------------------------

    @staticmethod
    def _extract_xmp_field(xmp_text: str, tag: str) -> str | None:
        match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", xmp_text, re.DOTALL)
        if match is None:
            return None
        stripped = re.sub(r"<[^>]+>", " ", match.group(1))
        cleaned = " ".join(stripped.split())
        return cleaned[:_MAX_PREVIEW] if cleaned else None

    # -- trailing data ----------------------------------------------------------

    def _find_scan_eoi(self, content: bytes, offset: int) -> int | None:
        in_scan = True
        while offset < len(content):
            if in_scan:
                marker_offset = self._next_scan_marker(content, offset)
                if marker_offset is None:
                    return None
                offset = marker_offset
                in_scan = False
            if content[offset] != 0xFF:
                return None
            while offset < len(content) and content[offset] == 0xFF:
                offset += 1
            if offset >= len(content):
                return None
            marker = content[offset]
            offset += 1
            if marker == 0xD9:
                return offset
            if marker == 0x01 or 0xD0 <= marker <= 0xD7:
                continue
            if offset + 2 > len(content):
                return None
            length = struct.unpack_from(">H", content, offset)[0]
            if length < 2 or offset + length > len(content):
                return None
            offset += length
            if marker == 0xDA:
                in_scan = True
        return None

    @staticmethod
    def _next_scan_marker(content: bytes, offset: int) -> int | None:
        while offset + 1 < len(content):
            if content[offset] != 0xFF:
                offset += 1
                continue
            next_byte = content[offset + 1]
            if next_byte == 0x00 or 0xD0 <= next_byte <= 0xD7:
                offset += 2
                continue
            if next_byte == 0xFF:
                offset += 1
                continue
            return offset
        return None

    def _analyze_trailing(
        self, content: bytes, start_offset: int
    ) -> JpegTrailingDataResult | None:
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

        return JpegTrailingDataResult(
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
