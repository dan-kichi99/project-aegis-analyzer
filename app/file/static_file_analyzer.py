from app.file.file_analysis_result import FileAnalysisResult
from app.file.file_input import FileInput
from app.file.file_type_detector import FileTypeDetector

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

        return FileAnalysisResult(
            name=file_input.name,
            size=file_input.size,
            extension=file_input.extension,
            detected_type=detected_type,
            text_content=text_content,
            strings=extracted_strings,
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
