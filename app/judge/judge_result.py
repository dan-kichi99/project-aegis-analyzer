from dataclasses import dataclass


@dataclass(slots=True)
class JudgeResult:
    """Judgeの判定結果および評価情報を保持するデータ構造 (DTO)"""

    category: str
    answer: str
    flag: str | None = None
    confidence: int | None = None
    reason: str | None = None
    hypothesis: str | None = None
    next_actions: list[str] | None = None
    gemini_prompt: str | None = None
