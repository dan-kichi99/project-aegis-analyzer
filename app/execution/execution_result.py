from dataclasses import dataclass
from enum import Enum


class ExecutionStatus(str, Enum):
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    REJECTED = "rejected"
    FAILED = "failed"


class ExecutionFailureReason(str, Enum):
    NOT_PYTHON = "not_python"
    NOT_APPROVED = "not_approved"
    NO_SAFETY_RESULT = "no_safety_result"
    UNPARSEABLE = "unparseable"
    RISK_NOT_LOW = "risk_not_low"
    INVALID_INDEX = "invalid_index"
    EMPTY_CODE = "empty_code"
    CODE_TOO_LARGE = "code_too_large"
    START_FAILED = "start_failed"
    TIMED_OUT = "timed_out"
    OUTPUT_LIMIT_EXCEEDED = "output_limit_exceeded"
    CLEANUP_FAILED = "cleanup_failed"


@dataclass(slots=True, frozen=True)
class PythonExecutionResult:
    status: ExecutionStatus
    started: bool
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    duration_seconds: float
    failure_reason: ExecutionFailureReason | None
    message: str
    output_truncated: bool
    cleanup_succeeded: bool

