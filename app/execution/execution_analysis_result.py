from dataclasses import dataclass
from enum import Enum

from app.execution.execution_result import PythonExecutionResult


class ExecutionOutputSource(str, Enum):
    STDOUT = "stdout"
    STDERR = "stderr"


@dataclass(slots=True, frozen=True)
class ExecutionFlagCandidate:
    flag: str
    source: ExecutionOutputSource
    position: int


@dataclass(slots=True, frozen=True)
class ExecutionAnalysisResult:
    execution: PythonExecutionResult
    flag_candidates: tuple[ExecutionFlagCandidate, ...]
    primary_flag: str | None
    successful_execution: bool
    source_index: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.source_index, bool):
            raise TypeError("source_indexにboolは指定できません。")
        if self.source_index is not None and not isinstance(self.source_index, int):
            raise TypeError("source_indexは整数またはNoneで指定してください。")
        if self.source_index is not None and self.source_index < 0:
            raise ValueError("source_indexは0以上またはNoneで指定してください。")
