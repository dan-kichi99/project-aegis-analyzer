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

