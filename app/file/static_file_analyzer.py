from app.file.appended_data_analyzer import AppendedDataAnalyzer
from app.file.archive_analyzer import ArchiveAnalyzer, archive_summary_strings
from app.file.common_encoding_decoder import decode_common_encoding
from app.file.elf_analyzer import ElfAnalyzer
from app.file.file_analysis_result import FileAnalysisResult
from app.file.file_input import FileInput
from app.file.file_type_detector import FileTypeDetector
from app.file.image_metadata_extractor import extract_image_metadata
from app.file.pdf_static_analyzer import PdfStaticAnalyzer, pdf_static_summary_strings
from app.file.pe_analyzer import PeAnalyzer
from app.file.png_metadata_analyzer import (
    PngMetadataAnalyzer,
    png_metadata_summary_strings,
)
from app.file.rev_clue_analyzer import RevClueAnalyzer
from app.solver.caesar_analyzer import CaesarAnalyzer
from app.solver.recursive_encoding_analyzer import RecursiveEncodingAnalyzer
from app.solver.single_byte_xor_analyzer import SingleByteXorAnalyzer

_ANALYSIS_BYTE_LIMIT = 2_000_000
_MIN_STRING_LENGTH = 4
_MAX_STRINGS = 200
_MAX_REV_STRINGS = 500
_MAX_STRING_LENGTH = 300


class StaticFileAnalyzer:
    """ローカルファイルから実行せずに安全な静的特徴および strings を抽出するアナライザー。"""

    def __init__(
        self,
        type_detector: FileTypeDetector | None = None,
    ) -> None:
        self.type_detector = type_detector or FileTypeDetector()
        self._pe_analyzer = PeAnalyzer()
        self._elf_analyzer = ElfAnalyzer()
        self._rev_clue_analyzer = RevClueAnalyzer()
        self._xor_analyzer = SingleByteXorAnalyzer()
        self._caesar_analyzer = CaesarAnalyzer()
        self._appended_data_analyzer = AppendedDataAnalyzer(self.type_detector)
        self._archive_analyzer = ArchiveAnalyzer()
        self._recursive_encoding_analyzer = RecursiveEncodingAnalyzer()
        self._png_metadata_analyzer = PngMetadataAnalyzer()
        self._pdf_static_analyzer = PdfStaticAnalyzer()

    def analyze(self, file_input: FileInput) -> FileAnalysisResult:
        detected_type = self.type_detector.detect(file_input)

        # 先頭2MBのみを解析対象とする
        analysis_content = file_input.content[:_ANALYSIS_BYTE_LIMIT]

        # Text 形式の場合のみ UTF-8 decode を試行
        text_content: str | None = None
        if detected_type == "text":
            try:
                text_content = analysis_content.decode("utf-8")
            except UnicodeDecodeError:
                text_content = None

        # Printable strings 抽出
        max_strings = (
            _MAX_REV_STRINGS
            if detected_type in {"pe", "elf", "mach-o"}
            else _MAX_STRINGS
        )
        extracted_strings = self._extract_printable_strings(
            analysis_content, max_strings
        )
        self._append_unique_strings(
            extracted_strings,
            self._extract_utf16le_strings(analysis_content, max_strings),
            max_strings,
        )
        self._append_unique_strings(
            extracted_strings,
            self._extract_short_rev_markers(analysis_content),
            max_strings,
        )
        self._append_unique_strings(
            extracted_strings,
            extract_image_metadata(analysis_content, detected_type),
            max_strings,
        )
        self._append_decoded_strings(
            extracted_strings,
            text_content,
            max_strings,
        )
        if detected_type == "zip":
            archive_result = self._archive_analyzer.analyze(file_input.content)
            if archive_result is not None:
                self._append_unique_strings(
                    extracted_strings,
                    archive_summary_strings(archive_result),
                    max_strings,
                )
        if detected_type == "png":
            # PNG構造解析は先頭2MB制限の対象外とし、50MB上限まで全体を読み込む。
            png_metadata_result = self._png_metadata_analyzer.analyze(
                file_input.content
            )
            self._append_unique_strings(
                extracted_strings,
                png_metadata_summary_strings(png_metadata_result),
                max_strings,
            )
        if detected_type == "pdf":
            # PDF構造解析は先頭2MB制限の対象外とし、50MB上限まで全体を読み込む。
            pdf_static_result = self._pdf_static_analyzer.analyze(file_input.content)
            self._append_unique_strings(
                extracted_strings,
                pdf_static_summary_strings(pdf_static_result),
                max_strings,
            )
        pe_info = (
            self._pe_analyzer.analyze(file_input)
            if detected_type == "pe"
            else None
        )
        elf_info = (
            self._elf_analyzer.analyze(file_input)
            if detected_type == "elf"
            else None
        )
        rev_clues = (
            self._rev_clue_analyzer.analyze(extracted_strings)
            if detected_type in {"pe", "elf", "mach-o"}
            else None
        )
        xor_result = self._xor_analyzer.analyze(
            content=analysis_content,
            detected_type=detected_type,
            extension=file_input.extension,
            text_content=text_content,
            strings=extracted_strings,
        )
        caesar_result = self._caesar_analyzer.analyze(
            text_content=text_content,
            strings=extracted_strings,
        )
        appended_data = self._appended_data_analyzer.analyze(
            file_input=file_input,
            detected_type=detected_type,
            pe_info=pe_info,
            elf_info=elf_info,
        )
        recursive_encoding_result = self._recursive_encoding_analyzer.analyze(
            text_content=text_content,
            strings=extracted_strings,
        )

        return FileAnalysisResult(
            name=file_input.name,
            size=file_input.size,
            extension=file_input.extension,
            detected_type=detected_type,
            text_content=text_content,
            strings=extracted_strings,
            pe_info=pe_info,
            elf_info=elf_info,
            rev_clues=rev_clues,
            xor_result=xor_result,
            caesar_result=caesar_result,
            appended_data=appended_data,
            recursive_encoding_result=recursive_encoding_result,
        )

    def _extract_printable_strings(
        self, content: bytes, max_strings: int
    ) -> list[str]:
        results: list[str] = []
        current_chars: list[str] = []

        for byte in content:
            if 0x20 <= byte <= 0x7E:
                current_chars.append(chr(byte))
            else:
                if len(current_chars) >= _MIN_STRING_LENGTH:
                    results.append("".join(current_chars)[:_MAX_STRING_LENGTH])
                    if len(results) >= max_strings:
                        return results
                current_chars = []

        if (
            len(current_chars) >= _MIN_STRING_LENGTH
            and len(results) < max_strings
        ):
            results.append("".join(current_chars)[:_MAX_STRING_LENGTH])
        return results

    def _extract_utf16le_strings(
        self, content: bytes, max_strings: int
    ) -> list[str]:
        results: list[str] = []
        seen: set[str] = set()
        for alignment in (0, 1):
            current: list[str] = []
            for index in range(alignment, len(content) - 1, 2):
                low, high = content[index], content[index + 1]
                if high == 0 and 0x20 <= low <= 0x7E:
                    if (
                        not current
                        and index > 0
                        and 0x20 <= content[index - 1] <= 0x7E
                    ):
                        continue
                    current.append(chr(low))
                    continue
                self._append_utf16_string(results, seen, current)
                current = []
                if len(results) >= max_strings:
                    return results
            self._append_utf16_string(results, seen, current)
        return results

    @staticmethod
    def _append_utf16_string(
        results: list[str],
        seen: set[str],
        characters: list[str],
    ) -> None:
        if len(characters) < _MIN_STRING_LENGTH:
            return
        value = "".join(characters)[:_MAX_STRING_LENGTH]
        if value not in seen:
            seen.add(value)
            results.append(value)

    @staticmethod
    def _extract_short_rev_markers(content: bytes) -> list[str]:
        return [
            marker.decode("ascii")
            for marker in (b"GCC", b"PDB")
            if marker in content
        ]

    def _append_unique_strings(
        self,
        extracted_strings: list[str],
        additional_strings: list[str],
        max_strings: int,
    ) -> None:
        known_strings = set(extracted_strings)
        for value in additional_strings:
            if len(extracted_strings) >= max_strings:
                return
            bounded = value[:_MAX_STRING_LENGTH]
            if bounded and bounded not in known_strings:
                extracted_strings.append(bounded)
                known_strings.add(bounded)

    def _append_decoded_strings(
        self,
        extracted_strings: list[str],
        text_content: str | None,
        max_strings: int,
    ) -> None:
        original_strings = extracted_strings.copy()
        candidate_sources = original_strings.copy()
        if text_content is not None:
            candidate_sources.extend(text_content.splitlines())

        candidates: list[str] = []
        seen_candidates: set[str] = set()
        for source in candidate_sources:
            for candidate in (source.strip(), *source.split()):
                if candidate and candidate not in seen_candidates:
                    seen_candidates.add(candidate)
                    candidates.append(candidate)
                    if len(candidates) >= max_strings:
                        break
            if len(candidates) >= max_strings:
                break

        known_strings = set(extracted_strings)
        for candidate in candidates:
            if len(extracted_strings) >= max_strings:
                return

            decoded = decode_common_encoding(candidate)
            if decoded is not None and decoded not in known_strings:
                extracted_strings.append(decoded)
                known_strings.add(decoded)
