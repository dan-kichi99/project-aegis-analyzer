import base64
import re
import zlib

from app.file.pdf_static_result import (
    PdfMetadataItem,
    PdfObjectItem,
    PdfStaticResult,
    PdfSuspiciousItem,
    PdfTrailingDataResult,
)
from app.judge.flag_extractor import FlagExtractor

_HEADER_MARKER = b"%PDF-"
_HEADER_SEARCH_WINDOW = 1024
_VERSION_PATTERN = re.compile(rb"%PDF-(\d\.\d)")

_MAX_FILE_SIZE = 50_000_000
_MAX_OBJECTS = 500
_MAX_OBJECT_SCAN = 2_000_000
_MAX_METADATA_ITEMS = 200
_MAX_COMMENTS = 100
_MAX_SUSPICIOUS_ITEMS = 200
_MAX_KEYS_PER_OBJECT = 40
_MAX_STREAM_ANALYSIS = 1_000_000
_MAX_ZLIB_OUTPUT = 1_000_000
_MAX_TRAILING_BYTES = 1_000_000
_MAX_PREVIEW = 500
_MAX_VALUE_LENGTH = 2_000
_MAX_STRINGS = 100
_MAX_FLAGS = 100
_MIN_STRING_LENGTH = 4
_MAX_STRING_LENGTH = 300
_MAX_GLOBAL_STRING_SCAN = 300

_OBJECT_PATTERN = re.compile(r"(?<!\d)(\d{1,7})[ \t]+(\d{1,5})[ \t]+obj\b")
_ENDOBJ_PATTERN = re.compile(r"\bendobj\b")
_STREAM_PATTERN = re.compile(r"(?<!end)\bstream\b")
_ENDSTREAM_PATTERN = re.compile(r"\bendstream\b")
_DICT_KEY_PATTERN = re.compile(r"/([A-Za-z][A-Za-z0-9]{0,63})")
_LITERAL_STRING_PATTERN = re.compile(r"\(((?:[^()\\]|\\.)*)\)")
_HEX_STRING_PATTERN = re.compile(r"<([0-9A-Fa-f\s]{2,4000})>(?!>)")
_XREF_PATTERN = re.compile(r"(?<![A-Za-z])xref\b")

_META_KEYS = (
    "Author",
    "Creator",
    "Producer",
    "Title",
    "Subject",
    "Keywords",
    "CreationDate",
    "ModDate",
)
_META_KEY_PATTERN = re.compile(
    r"/(" + "|".join(_META_KEYS) + r")\s*(\((?:[^()\\]|\\.)*\)|<[0-9A-Fa-f\s]*>)"
)

_IMPORTANT_KEYWORDS = (
    "flag",
    "password",
    "secret",
    "key",
    "hint",
    "author",
    "creator",
    "title",
    "subject",
    "keyword",
    "comment",
    "hidden",
    "embedded",
    "javascript",
    "encoded",
)

_SUSPICIOUS_MARKERS = (
    "/JavaScript",
    "/JS",
    "/OpenAction",
    "/AA",
    "/Launch",
    "/URI",
    "/EmbeddedFile",
    "/Filespec",
    "/AcroForm",
    "/XFA",
    "/Encrypt",
)
_HIGH_SEVERITY_MARKERS = frozenset(
    {"/JavaScript", "/JS", "/OpenAction", "/AA", "/Launch"}
)

_SUPPORTED_FILTERS = ("/FlateDecode", "/ASCIIHexDecode", "/ASCII85Decode")
_UNSUPPORTED_FILTERS = (
    "/LZWDecode",
    "/RunLengthDecode",
    "/CCITTFaxDecode",
    "/DCTDecode",
    "/JPXDecode",
    "/Crypt",
)

_MAGIC_SIGNATURES = (
    (b"PK\x03\x04", "ZIP"),
    (b"PK\x05\x06", "ZIP"),
    (_HEADER_MARKER, "PDF"),
    (b"\x7fELF", "ELF"),
    (b"MZ", "PE"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x1f\x8b", "GZIP"),
)

PDF_METADATA_PREFIX = "__AEGIS_PDF_METADATA__:"
PDF_INFO_PREFIX = "__AEGIS_PDF_INFO__:"
PDF_WARNING_PREFIX = "__AEGIS_PDF_WARNING__:"
PDF_TRAILING_PREFIX = "__AEGIS_PDF_TRAILING__:"
PDF_FLAG_PREFIX = "__AEGIS_PDF_FLAG__:"

_EMPTY_RESULT = PdfStaticResult(
    valid_header=False,
    version=None,
    object_count=0,
    objects=(),
    metadata_items=(),
    comments=(),
    suspicious_items=(),
    warnings=(),
    flag_candidates=(),
    trailing_data=None,
    encrypted=False,
    truncated=False,
)


def pdf_static_summary_strings(result: PdfStaticResult) -> list[str]:
    """PdfStaticResultを予約prefix付きの安全なsummary文字列へ変換する。"""
    if not result.valid_header:
        return []
    values: list[str] = []
    version = result.version or "unknown"
    values.append(
        f"{PDF_METADATA_PREFIX}version={version} objects={result.object_count} "
        f"encrypted={'true' if result.encrypted else 'false'}"
    )
    for item in result.metadata_items:
        values.append(f"{PDF_INFO_PREFIX}{item.key}={item.value_preview}")
    for warning in result.warnings:
        values.append(f"{PDF_WARNING_PREFIX}{warning}")
    if result.trailing_data is not None:
        magic = result.trailing_data.detected_magic or "unknown"
        values.append(
            f"{PDF_TRAILING_PREFIX}size={result.trailing_data.size} magic={magic}"
        )
    for flag in result.flag_candidates:
        values.append(f"{PDF_FLAG_PREFIX}candidate={flag}")
    return values


class PdfStaticAnalyzer:
    """PDFの構造・メタデータ・危険痕跡・IEND(EOF)後データを安全に静的解析する。"""

    def __init__(self, flag_extractor: FlagExtractor | None = None) -> None:
        self._flag_extractor = flag_extractor or FlagExtractor()

    def analyze(self, content: bytes) -> PdfStaticResult:
        header_offset = content[:_HEADER_SEARCH_WINDOW].find(_HEADER_MARKER)
        if header_offset < 0:
            return _EMPTY_RESULT
        if len(content) > _MAX_FILE_SIZE:
            return PdfStaticResult(
                valid_header=True,
                version=None,
                object_count=0,
                objects=(),
                metadata_items=(),
                comments=(),
                suspicious_items=(),
                warnings=("ファイルサイズが上限（50MB）を超えているため解析を中止しました。",),
                flag_candidates=(),
                trailing_data=None,
                encrypted=False,
                truncated=True,
            )

        version = self._extract_version(content)
        text = content.decode("latin-1")

        warnings: list[str] = []
        flag_candidates: list[str] = []
        seen_flags: set[str] = set()

        objects, objects_truncated = self._find_objects(content, text, warnings)
        comments = self._find_comments(text)
        metadata_items = self._find_metadata(text, warnings)
        suspicious_items = self._find_suspicious(text, warnings)
        trailing_data = self._find_trailing_data(content, text)
        encrypted = "/Encrypt" in text

        self._check_structure(text, warnings)

        for item in metadata_items:
            self._merge_flags(flag_candidates, seen_flags, item.flag_candidates)
        for item in objects:
            self._merge_flags(flag_candidates, seen_flags, item.flag_candidates)
        for comment in comments:
            self._merge_flags(
                flag_candidates, seen_flags, self._flag_extractor.extract_all(comment)
            )
        if trailing_data is not None:
            self._merge_flags(
                flag_candidates, seen_flags, trailing_data.flag_candidates
            )
        self._merge_flags(
            flag_candidates, seen_flags, self._scan_global_strings(text)
        )

        return PdfStaticResult(
            valid_header=True,
            version=version,
            object_count=len(objects),
            objects=tuple(objects),
            metadata_items=tuple(metadata_items),
            comments=tuple(comments),
            suspicious_items=tuple(suspicious_items),
            warnings=tuple(warnings),
            flag_candidates=tuple(flag_candidates[:_MAX_FLAGS]),
            trailing_data=trailing_data,
            encrypted=encrypted,
            truncated=objects_truncated,
        )

    # -- header -----------------------------------------------------------

    @staticmethod
    def _extract_version(content: bytes) -> str | None:
        match = _VERSION_PATTERN.search(content[:_HEADER_SEARCH_WINDOW])
        return match.group(1).decode("ascii") if match else None

    # -- objects ------------------------------------------------------------

    def _find_objects(
        self, content: bytes, text: str, warnings: list[str]
    ) -> tuple[list[PdfObjectItem], bool]:
        matches = list(_OBJECT_PATTERN.finditer(text))
        objects: list[PdfObjectItem] = []
        truncated = False
        broken_objects: list[str] = []

        for index, match in enumerate(matches):
            if len(objects) >= _MAX_OBJECTS:
                warnings.append("object数が上限を超えたため解析を打ち切りました。")
                truncated = True
                break

            object_number = int(match.group(1))
            generation_number = int(match.group(2))
            offset = match.start()

            if object_number == 0:
                warnings.append(f"object {object_number} {generation_number}: 無効なobject番号です。")
            if generation_number > 65535:
                warnings.append(
                    f"object {object_number} {generation_number}: 無効なgeneration番号です。"
                )

            next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            search_limit = min(next_start, match.end() + _MAX_OBJECT_SCAN)
            endobj_match = _ENDOBJ_PATTERN.search(text, match.end(), search_limit)
            item_truncated = endobj_match is None
            body_end = endobj_match.start() if endobj_match is not None else search_limit
            body = text[match.end() : body_end]

            if item_truncated:
                broken_objects.append(f"{object_number} {generation_number}")

            has_stream, stream_flags = self._process_stream(
                content, text, match.end(), body_end, body, warnings
            )

            keys = tuple(sorted(set(_DICT_KEY_PATTERN.findall(body)))[:_MAX_KEYS_PER_OBJECT])
            suspicious_markers = tuple(
                marker for marker in _SUSPICIOUS_MARKERS if marker in body
            )
            preview = self._sanitize_preview(body[:_MAX_PREVIEW])
            value_truncated = len(body) > _MAX_PREVIEW or item_truncated

            flags: list[str] = []
            seen: set[str] = set()
            self._merge_flags(flags, seen, self._flag_extractor.extract_all(preview))
            self._merge_flags(flags, seen, stream_flags)

            objects.append(
                PdfObjectItem(
                    object_number=object_number,
                    generation_number=generation_number,
                    offset=offset,
                    has_stream=has_stream,
                    keys=keys,
                    preview=preview,
                    suspicious_markers=suspicious_markers,
                    flag_candidates=tuple(flags[:_MAX_FLAGS]),
                    truncated=value_truncated,
                )
            )

        if broken_objects:
            warnings.append(
                "endobjで閉じられていないobjectを検出しました：" + ", ".join(broken_objects[:10])
            )
        return objects, truncated

    def _process_stream(
        self,
        content: bytes,
        text: str,
        body_start: int,
        body_end: int,
        body: str,
        warnings: list[str],
    ) -> tuple[bool, list[str]]:
        stream_match = _STREAM_PATTERN.search(body)
        if stream_match is None:
            return False, []

        dict_portion = body[: stream_match.start()]
        stream_keyword_start = body_start + stream_match.end()
        data_start = stream_keyword_start
        if content[data_start : data_start + 2] == b"\r\n":
            data_start += 2
        elif content[data_start : data_start + 1] == b"\n":
            data_start += 1

        endstream_match = _ENDSTREAM_PATTERN.search(text, data_start, body_end)
        if endstream_match is None:
            warnings.append("stream/endstreamの対応が取れていないchunkを検出しました。")
            return True, []

        data_end = endstream_match.start()
        while data_end > data_start and content[data_end - 1 : data_end] in (b"\r", b"\n"):
            data_end -= 1

        raw_length = data_end - data_start
        if raw_length > _MAX_STREAM_ANALYSIS:
            warnings.append("異常に大きなstreamを検出したため展開を中止しました。")
            return True, []

        stream_bytes = content[data_start:data_end]
        decoded = self._decode_stream(dict_portion, stream_bytes, warnings)
        if decoded is None:
            return True, []
        preview = self._sanitize_preview(
            decoded.decode("latin-1", errors="replace")[:_MAX_VALUE_LENGTH]
        )
        return True, self._flag_extractor.extract_all(preview)

    def _decode_stream(
        self, dict_portion: str, stream_bytes: bytes, warnings: list[str]
    ) -> bytes | None:
        if any(filt in dict_portion for filt in _UNSUPPORTED_FILTERS):
            return None
        if "/FlateDecode" in dict_portion:
            decoded = self._limited_inflate(stream_bytes)
            if decoded is None:
                warnings.append("FlateDecodeの展開に失敗またはサイズ上限を超えました。")
            return decoded
        if "/ASCIIHexDecode" in dict_portion:
            return self._decode_ascii_hex(stream_bytes)
        if "/ASCII85Decode" in dict_portion:
            return self._decode_ascii85(stream_bytes)
        return None

    @staticmethod
    def _limited_inflate(data: bytes) -> bytes | None:
        decompressor = zlib.decompressobj()
        try:
            decoded = decompressor.decompress(data, _MAX_ZLIB_OUTPUT + 1)
            if len(decoded) > _MAX_ZLIB_OUTPUT or decompressor.unconsumed_tail:
                return None
            decoded += decompressor.flush()
        except zlib.error:
            return None
        return decoded if len(decoded) <= _MAX_ZLIB_OUTPUT else None

    @staticmethod
    def _decode_ascii_hex(data: bytes) -> bytes | None:
        cleaned = data.split(b">", 1)[0]
        cleaned = bytes(b for b in cleaned if b not in b" \t\r\n")
        if len(cleaned) % 2 != 0:
            cleaned += b"0"
        try:
            return bytes.fromhex(cleaned.decode("ascii"))
        except ValueError:
            return None

    @staticmethod
    def _decode_ascii85(data: bytes) -> bytes | None:
        try:
            return base64.a85decode(data, adobe=True)
        except ValueError:
            try:
                return base64.a85decode(data.split(b"~>", 1)[0])
            except ValueError:
                return None

    # -- metadata -----------------------------------------------------------

    def _find_metadata(
        self, text: str, warnings: list[str]
    ) -> list[PdfMetadataItem]:
        items: list[PdfMetadataItem] = []
        for match in _META_KEY_PATTERN.finditer(text):
            if len(items) >= _MAX_METADATA_ITEMS:
                warnings.append("metadata件数が上限を超えたため打ち切りました。")
                break
            key = match.group(1)
            raw_value = match.group(2)
            value = self._decode_pdf_string(raw_value)
            truncated = len(value) > _MAX_VALUE_LENGTH
            limited = value[:_MAX_VALUE_LENGTH]
            preview = self._sanitize_preview(limited[:_MAX_PREVIEW])
            if len(limited) > _MAX_PREVIEW:
                truncated = True
            important = self._is_important(key)
            flags = self._flag_extractor.extract_all(preview)
            items.append(
                PdfMetadataItem(
                    key=key,
                    value_preview=preview,
                    offset=match.start(),
                    important=important,
                    flag_candidates=tuple(flags[:_MAX_FLAGS]),
                    truncated=truncated,
                )
            )
        return items

    @staticmethod
    def _decode_pdf_string(raw: str) -> str:
        if raw.startswith("<"):
            hex_digits = "".join(ch for ch in raw[1:-1] if not ch.isspace())
            if len(hex_digits) % 2 != 0:
                hex_digits += "0"
            try:
                raw_bytes = bytes.fromhex(hex_digits)
            except ValueError:
                return ""
            if raw_bytes.startswith(b"\xfe\xff"):
                try:
                    return raw_bytes[2:].decode("utf-16-be", errors="replace")
                except UnicodeDecodeError:
                    return raw_bytes.decode("latin-1", errors="replace")
            return raw_bytes.decode("latin-1", errors="replace")

        inner = raw[1:-1]
        unescaped = (
            inner.replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\")
        )
        raw_bytes = unescaped.encode("latin-1", errors="replace")
        if raw_bytes.startswith(b"\xfe\xff"):
            try:
                return raw_bytes[2:].decode("utf-16-be", errors="replace")
            except UnicodeDecodeError:
                pass
        return unescaped

    @staticmethod
    def _is_important(key: str) -> bool:
        lowered = key.lower()
        return any(word in lowered for word in _IMPORTANT_KEYWORDS)

    # -- comments -------------------------------------------------------------

    def _find_comments(self, text: str) -> tuple[str, ...]:
        comments: list[str] = []
        for line in text.splitlines():
            if len(comments) >= _MAX_COMMENTS:
                break
            stripped = line.strip()
            if not stripped.startswith("%") or stripped.startswith("%PDF-"):
                continue
            if stripped.startswith("%%EOF"):
                continue
            body = stripped[1:]
            printable = sum(1 for ch in body if 0x20 <= ord(ch) <= 0x7E)
            if body and printable / len(body) < 0.5:
                continue
            comments.append(self._sanitize_preview(body.strip()[:_MAX_PREVIEW]))
        return tuple(comments)

    # -- suspicious markers ---------------------------------------------------

    def _find_suspicious(
        self, text: str, warnings: list[str]
    ) -> tuple[PdfSuspiciousItem, ...]:
        items: list[PdfSuspiciousItem] = []
        for marker in _SUSPICIOUS_MARKERS:
            if len(items) >= _MAX_SUSPICIOUS_ITEMS:
                break
            match = re.search(re.escape(marker) + r"\b", text)
            if match is None:
                continue
            severity = "high" if marker in _HIGH_SEVERITY_MARKERS else "medium"
            detail = self._sanitize_preview(
                text[match.start() : match.start() + _MAX_PREVIEW]
            )
            items.append(
                PdfSuspiciousItem(
                    item_type=marker.lstrip("/"),
                    object_number=None,
                    offset=match.start(),
                    detail_preview=detail,
                    severity=severity,
                )
            )
            label = {
                "/JavaScript": "javascript",
                "/JS": "javascript",
                "/Launch": "launch",
                "/EmbeddedFile": "embedded_file",
                "/Encrypt": "encrypt",
            }.get(marker)
            if label is not None:
                warnings.append(f"{label} object=不明（offset 0x{match.start():X}）")
        return tuple(items)

    # -- structural warnings ---------------------------------------------------

    def _check_structure(self, text: str, warnings: list[str]) -> None:
        if text.count("%%EOF") == 0:
            warnings.append("%%EOFが見つかりません。")
        elif text.count("%%EOF") > 1:
            warnings.append("%%EOFが複数回出現しています。")
        if "startxref" not in text:
            warnings.append("startxrefが見つかりません。")
        if _XREF_PATTERN.search(text) is None:
            warnings.append("xrefが見つかりません。")
        if "trailer" not in text:
            warnings.append("trailerが見つかりません。")

        obj_count = len(_OBJECT_PATTERN.findall(text))
        endobj_count = len(_ENDOBJ_PATTERN.findall(text))
        if obj_count != endobj_count:
            warnings.append("objectとendobjの数が一致しません。")

        stream_count = len(_STREAM_PATTERN.findall(text))
        endstream_count = len(_ENDSTREAM_PATTERN.findall(text))
        if stream_count != endstream_count:
            warnings.append("streamとendstreamの数が一致しません。")

    # -- trailing data ----------------------------------------------------------

    def _find_trailing_data(
        self, content: bytes, text: str
    ) -> PdfTrailingDataResult | None:
        last_eof = text.rfind("%%EOF")
        if last_eof < 0:
            return None
        start_offset = last_eof + len("%%EOF")
        while start_offset < len(content) and content[start_offset] in b"\r\n":
            start_offset += 1
        if start_offset >= len(content):
            return None

        remaining = content[start_offset:]
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

        return PdfTrailingDataResult(
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

    # -- global string/flag scan ---------------------------------------------

    def _scan_global_strings(self, text: str) -> list[str]:
        flags: list[str] = []
        seen: set[str] = set()
        for index, match in enumerate(_LITERAL_STRING_PATTERN.finditer(text)):
            if index >= _MAX_GLOBAL_STRING_SCAN:
                break
            value = self._decode_pdf_string("(" + match.group(1) + ")")
            self._merge_flags(flags, seen, self._flag_extractor.extract_all(value))
        for index, match in enumerate(_HEX_STRING_PATTERN.finditer(text)):
            if index >= _MAX_GLOBAL_STRING_SCAN:
                break
            value = self._decode_pdf_string("<" + match.group(1) + ">")
            self._merge_flags(flags, seen, self._flag_extractor.extract_all(value))
        return flags

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
