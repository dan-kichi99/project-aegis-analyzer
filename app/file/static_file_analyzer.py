from app.file.common_encoding_decoder import decode_common_encoding
from app.file.file_analysis_result import FileAnalysisResult
from app.file.file_input import FileInput
from app.file.file_type_detector import FileTypeDetector
from app.file.image_metadata_extractor import extract_image_metadata
from app.file.pe_analyzer import PeAnalyzer

_ANALYSIS_BYTE_LIMIT = 2_000_000
_MIN_STRING_LENGTH = 4
_MAX_STRINGS = 200


class StaticFileAnalyzer:
    """ローカルファイルから実行せずに安全な静的特徴および strings を抽出するアナライザー。"""

    def __init__(
        self,
        type_detector: FileTypeDetector | None = None,
    ) -> None:
        self.type_detector = type_detector or FileTypeDetector()
        self._pe_analyzer = PeAnalyzer()

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
        extracted_strings = self._extract_printable_strings(analysis_content)
        self._append_unique_strings(
            extracted_strings,
            extract_image_metadata(analysis_content, detected_type),
        )
        self._append_decoded_strings(
            extracted_strings,
            text_content,
        )
        pe_info = (
            self._pe_analyzer.analyze(file_input)
            if detected_type == "pe"
            else None
        )

        return FileAnalysisResult(
            name=file_input.name,
            size=file_input.size,
            extension=file_input.extension,
            detected_type=detected_type,
            text_content=text_content,
            strings=extracted_strings,
            pe_info=pe_info,
        )

    def _extract_printable_strings(self, content: bytes) -> list[str]:
        results: list[str] = []
        current_chars: list[str] = []

        for byte in content:
            if 0x20 <= byte <= 0x7E:
                current_chars.append(chr(byte))
            else:
                if len(current_chars) >= _MIN_STRING_LENGTH:
                    results.append("".join(current_chars))
                    if len(results) >= _MAX_STRINGS:
                        return results
                current_chars = []

        if (
            len(current_chars) >= _MIN_STRING_LENGTH
            and len(results) < _MAX_STRINGS
        ):
            results.append("".join(current_chars))
        return results

    def _append_unique_strings(
        self,
        extracted_strings: list[str],
        additional_strings: list[str],
    ) -> None:
        known_strings = set(extracted_strings)
        for value in additional_strings:
            if len(extracted_strings) >= _MAX_STRINGS:
                return
            if value and value not in known_strings:
                extracted_strings.append(value)
                known_strings.add(value)

    def _append_decoded_strings(
        self,
        extracted_strings: list[str],
        text_content: str | None,
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
                    if len(candidates) >= _MAX_STRINGS:
                        break
            if len(candidates) >= _MAX_STRINGS:
                break

        known_strings = set(extracted_strings)
        for candidate in candidates:
            if len(extracted_strings) >= _MAX_STRINGS:
                return

            decoded = decode_common_encoding(candidate)
            if decoded is not None and decoded not in known_strings:
                extracted_strings.append(decoded)
                known_strings.add(decoded)
