from dataclasses import dataclass, field

from app.file.file_analysis_result import FileAnalysisResult
from app.solver.rsa_result import RsaResult


@dataclass(slots=True)
class ChallengeInput:
    """問題文および添付ファイルの解析結果を統合して保持する DTO。"""

    question: str
    files: list[FileAnalysisResult] = field(default_factory=list)
    rsa_result: RsaResult | None = None
