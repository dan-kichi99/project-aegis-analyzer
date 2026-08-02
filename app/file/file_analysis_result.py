from dataclasses import dataclass

from app.file.pe_analysis_result import PeAnalysisResult


@dataclass(slots=True)
class FileAnalysisResult:
    """ローカルファイルから抽出された安全な静的特徴を保持する DTO。"""

    name: str
    size: int
    extension: str
    detected_type: str
    text_content: str | None
    strings: list[str]
    pe_info: PeAnalysisResult | None = None
