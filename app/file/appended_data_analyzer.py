import struct
import zlib
from pathlib import Path

from app.file.appended_data_result import AppendedDataResult
from app.file.elf_analysis_result import ElfAnalysisResult
from app.file.file_input import FileInput
from app.file.file_type_detector import FileTypeDetector
from app.file.pe_analysis_result import PeAnalysisResult

MAX_CONTENT_BYTES = 2_000_000
MAX_PREVIEW_CHARACTERS = 200
_PDF_SEARCH_BYTES = 1_000_000
_ZIP_EOCD_SEARCH_BYTES = MAX_CONTENT_BYTES + 65_557
_WHITESPACE = frozenset(b"\t\n\v\f\r ")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_EXTRA_SIGNATURES = (
    (b"\x1f\x8b", "gzip"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"Rar!\x1a\x07", "rar"),
)


class AppendedDataAnalyzer:
    """対応形式の正規終端後にある追加バイト列を安全に検出する。"""

    def __init__(self, type_detector: FileTypeDetector | None = None) -> None:
        self._type_detector = type_detector or FileTypeDetector()

    def analyze(
        self,
        file_input: FileInput,
        detected_type: str,
        pe_info: PeAnalysisResult | None = None,
        elf_info: ElfAnalysisResult | None = None,
    ) -> AppendedDataResult | None:
        try:
            end_offset = self._find_end(
                file_input.content,
                detected_type,
                pe_info,
                elf_info,
            )
        except (IndexError, OverflowError, struct.error, ValueError):
            return None
        if end_offset is None or not 0 <= end_offset <= len(file_input.content):
            return None

        appended_offset = end_offset
        while (
            appended_offset < len(file_input.content)
            and file_input.content[appended_offset] in _WHITESPACE
        ):
            appended_offset += 1
        if appended_offset >= len(file_input.content):
            return None

        appended = file_input.content[appended_offset:]
        held_content = appended[:MAX_CONTENT_BYTES]
        detected = self._detect_type(held_content)
        preview = self._preview(held_content)
        return AppendedDataResult(
            container_type=detected_type,
            end_offset=end_offset,
            appended_offset=appended_offset,
            appended_size=len(appended),
            detected_type=detected,
            signature=" ".join(f"{byte:02X}" for byte in appended[:8]),
            preview=preview,
            content=held_content,
        )

    def _find_end(
        self,
        content: bytes,
        detected_type: str,
        pe_info: PeAnalysisResult | None,
        elf_info: ElfAnalysisResult | None,
    ) -> int | None:
        if detected_type == "png":
            return self._png_end(content)
        if detected_type == "jpeg":
            return self._jpeg_end(content)
        if detected_type == "pdf":
            return self._pdf_end(content)
        if detected_type == "zip":
            return self._zip_end(content)
        if detected_type == "pe" and pe_info is not None:
            ends = [
                section.raw_offset + section.raw_size
                for section in pe_info.sections
                if section.raw_data_in_bounds
            ]
            return max(ends, default=None)
        if detected_type == "elf" and elf_info is not None:
            return self._elf_end(elf_info)
        return None

    def _png_end(self, content: bytes) -> int | None:
        if not content.startswith(_PNG_SIGNATURE):
            return None
        offset = len(_PNG_SIGNATURE)
        while offset + 12 <= len(content):
            length = struct.unpack_from(">I", content, offset)[0]
            chunk_end = offset + 12 + length
            if chunk_end > len(content):
                return None
            chunk_type = content[offset + 4 : offset + 8]
            chunk_data = content[offset + 8 : offset + 8 + length]
            expected_crc = struct.unpack_from(">I", content, chunk_end - 4)[0]
            if zlib.crc32(chunk_type + chunk_data) != expected_crc:
                return None
            if chunk_type == b"IEND":
                return chunk_end if length == 0 else None
            offset = chunk_end
        return None

    def _jpeg_end(self, content: bytes) -> int | None:
        if not content.startswith(b"\xff\xd8"):
            return None
        offset = 2
        in_scan = False
        while offset < len(content):
            if in_scan:
                marker_offset = self._next_jpeg_scan_marker(content, offset)
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
            if marker in {0xD8, 0x01, *range(0xD0, 0xD8)}:
                continue
            if offset + 2 > len(content):
                return None
            segment_length = struct.unpack_from(">H", content, offset)[0]
            if segment_length < 2 or offset + segment_length > len(content):
                return None
            offset += segment_length
            if marker == 0xDA:
                in_scan = True
        return None

    def _next_jpeg_scan_marker(self, content: bytes, offset: int) -> int | None:
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

    def _pdf_end(self, content: bytes) -> int | None:
        if not content.startswith(b"%PDF-"):
            return None
        search_start = max(0, len(content) - _PDF_SEARCH_BYTES)
        position = content.rfind(b"%%EOF", search_start)
        return position + 5 if position >= 0 else None

    def _zip_end(self, content: bytes) -> int | None:
        search_start = max(0, len(content) - _ZIP_EOCD_SEARCH_BYTES)
        position = content.rfind(b"PK\x05\x06", search_start)
        while position >= search_start:
            if position + 22 <= len(content):
                comment_length = struct.unpack_from("<H", content, position + 20)[0]
                end_offset = position + 22 + comment_length
                if end_offset <= len(content):
                    return end_offset
            position = content.rfind(b"PK\x05\x06", search_start, position)
        return None

    def _elf_end(self, elf_info: ElfAnalysisResult) -> int:
        is_64 = elf_info.elf_class == "ELF64"
        ends = [64 if is_64 else 52]
        ends.append(
            elf_info.program_header_offset
            + elf_info.program_header_count * (56 if is_64 else 32)
        )
        ends.append(
            elf_info.section_header_offset
            + elf_info.section_header_count * (64 if is_64 else 40)
        )
        ends.extend(
            section.file_offset + section.size
            for section in elf_info.sections
            if section.section_type != "SHT_NOBITS" and section.data_in_bounds
        )
        ends.extend(
            segment.file_offset + segment.file_size
            for segment in elf_info.segments
            if segment.data_in_bounds
        )
        return max(ends)

    def _detect_type(self, content: bytes) -> str:
        for signature, detected_type in _EXTRA_SIGNATURES:
            if content.startswith(signature):
                return detected_type
        temporary = FileInput(
            name="appended-data",
            path=Path("appended-data"),
            size=len(content),
            extension="",
            content=content,
        )
        detected = self._type_detector.detect(temporary)
        return detected if detected not in {"text", "empty"} else "unknown"

    def _preview(self, content: bytes) -> str | None:
        if not content:
            return None
        preview = content.decode("utf-8", errors="replace")
        return preview[:MAX_PREVIEW_CHARACTERS]
