from dataclasses import dataclass
from enum import Enum

from app.agents.agent_result import AgentType
from app.benchmark.benchmark_case import BenchmarkExpectedPath


class BenchmarkCaseStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    TIMED_OUT = "timed_out"


def _count(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer.")
    if value < 0:
        raise ValueError(f"{name} must be zero or greater.")


@dataclass(slots=True, frozen=True)
class BenchmarkExecutionResult:
    actual_path: BenchmarkExpectedPath
    solved: bool
    actual_flag: str | None = None
    ai_calls: int = 0
    agent_runs: int = 0
    external_tool_calls: int = 0
    agent_types: tuple[AgentType, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.solved, bool):
            raise TypeError("solved must be a boolean.")
        _count(self.ai_calls, "ai_calls")
        _count(self.agent_runs, "agent_runs")
        _count(self.external_tool_calls, "external_tool_calls")


@dataclass(slots=True, frozen=True)
class BenchmarkCaseResult:
    case_id: str
    status: BenchmarkCaseStatus
    actual_path: BenchmarkExpectedPath | None
    solved: bool
    actual_flag: str | None
    flag_correct: bool | None
    false_positive: bool
    ai_calls: int
    agent_runs: int
    external_tool_calls: int
    duration_seconds: float
    exception_type: str | None
    failure_reasons: tuple[str, ...]
    fingerprint: str

    def __post_init__(self) -> None:
        _count(self.ai_calls, "ai_calls")
        _count(self.agent_runs, "agent_runs")
        _count(self.external_tool_calls, "external_tool_calls")
        if self.duration_seconds < 0:
            raise ValueError("duration_seconds must be zero or greater.")
        if len(self.failure_reasons) > 20:
            raise ValueError("failure_reasons must not contain more than 20 items.")
        if any(len(reason) > 500 for reason in self.failure_reasons):
            raise ValueError("A failure reason must not exceed 500 characters.")


@dataclass(slots=True, frozen=True)
class BenchmarkSummary:
    total_cases: int
    passed_cases: int
    failed_cases: int
    error_cases: int
    timed_out_cases: int
    local_solution_cases: int
    agent_solution_cases: int
    ai_fallback_cases: int
    unresolved_cases: int
    safe_failure_cases: int
    false_positive_cases: int
    incorrect_flag_cases: int
    total_ai_calls: int
    total_agent_runs: int
    total_external_tool_calls: int
    average_duration_seconds: float
    max_duration_seconds: float
    p95_duration_seconds: float
    reproducible: bool
    deterministic: bool

    def __post_init__(self) -> None:
        count_fields = (
            "total_cases", "passed_cases", "failed_cases", "error_cases",
            "timed_out_cases", "local_solution_cases", "agent_solution_cases",
            "ai_fallback_cases", "unresolved_cases", "safe_failure_cases",
            "false_positive_cases", "incorrect_flag_cases", "total_ai_calls",
            "total_agent_runs", "total_external_tool_calls",
        )
        for name in count_fields:
            _count(getattr(self, name), name)
        if self.total_cases != (
            self.passed_cases + self.failed_cases + self.error_cases
            + self.timed_out_cases
        ):
            raise ValueError("Status counts must equal total_cases.")
        if self.total_cases != (
            self.local_solution_cases + self.agent_solution_cases
            + self.ai_fallback_cases + self.unresolved_cases
            + self.safe_failure_cases
        ):
            raise ValueError("Path counts must equal total_cases.")
        if min(
            self.average_duration_seconds,
            self.max_duration_seconds,
            self.p95_duration_seconds,
        ) < 0:
            raise ValueError("Duration summaries must be zero or greater.")


@dataclass(slots=True, frozen=True)
class BenchmarkRunResult:
    results: tuple[BenchmarkCaseResult, ...]
    summary: BenchmarkSummary

    def __post_init__(self) -> None:
        if len(self.results) != self.summary.total_cases:
            raise ValueError("Result count must equal summary.total_cases.")
