from dataclasses import dataclass
from enum import Enum

from app.agents.agent_result import AgentType
from app.file.file_input import FileInput


class BenchmarkCategory(str, Enum):
    CRYPTO = "crypto"
    REV = "rev"
    WEB = "web"
    FORENSICS = "forensics"
    MISC = "misc"
    SAFETY = "safety"
    INTEGRATION = "integration"


class BenchmarkExpectedPath(str, Enum):
    LOCAL_SOLUTION = "local_solution"
    AGENT_SOLUTION = "agent_solution"
    AI_FALLBACK = "ai_fallback"
    UNRESOLVED = "unresolved"
    SAFE_FAILURE = "safe_failure"


def _validate_optional_count(value: int | None, name: str) -> None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise TypeError(f"{name} must be an integer or None.")
    if value is not None and value < 0:
        raise ValueError(f"{name} must be zero or greater.")


@dataclass(slots=True, frozen=True)
class BenchmarkCase:
    case_id: str
    name: str
    category: BenchmarkCategory
    question: str
    files: tuple[FileInput, ...]
    expected_path: BenchmarkExpectedPath
    expected_flag: str | None = None
    expected_agent_types: tuple[AgentType, ...] = ()
    expected_ai_calls: int | None = None
    expected_tool_calls: int | None = None
    max_duration_seconds: float = 1.0
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.case_id or len(self.case_id) > 100:
            raise ValueError("case_id must contain 1 to 100 characters.")
        if not self.name or len(self.name) > 200:
            raise ValueError("name must contain 1 to 200 characters.")
        if len(self.question) > 20_000:
            raise ValueError("question must not exceed 20,000 characters.")
        if len(self.files) > 20:
            raise ValueError("files must not contain more than 20 items.")
        if len(self.notes) > 500:
            raise ValueError("notes must not exceed 500 characters.")
        _validate_optional_count(self.expected_ai_calls, "expected_ai_calls")
        _validate_optional_count(self.expected_tool_calls, "expected_tool_calls")
        if isinstance(self.max_duration_seconds, bool) or not isinstance(
            self.max_duration_seconds, (int, float)
        ):
            raise TypeError("max_duration_seconds must be a number.")
        if self.max_duration_seconds <= 0:
            raise ValueError("max_duration_seconds must be greater than zero.")
