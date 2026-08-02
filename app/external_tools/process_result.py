from dataclasses import dataclass
from enum import Enum
from math import isfinite

MAX_PROCESS_RESULT_OUTPUT_CHARACTERS = 65_536
MAX_PROCESS_ERROR_CHARACTERS = 500


class ExternalProcessStatus(str, Enum):
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    FAILED = "failed"
    REJECTED = "rejected"


@dataclass(slots=True, frozen=True)
class ExternalProcessResult:
    status: ExternalProcessStatus
    started: bool
    executable: str
    arguments: tuple[str, ...]
    stdout: str
    stderr: str
    exit_code: int | None
    duration_seconds: float
    timed_out: bool
    stdout_truncated: bool
    stderr_truncated: bool
    error_type: str | None
    error_message: str | None

    def __post_init__(self) -> None:
        if len(self.stdout) > MAX_PROCESS_RESULT_OUTPUT_CHARACTERS:
            raise ValueError("stdoutは65536文字以内で指定してください。")
        if len(self.stderr) > MAX_PROCESS_RESULT_OUTPUT_CHARACTERS:
            raise ValueError("stderrは65536文字以内で指定してください。")
        if (
            self.error_message is not None
            and len(self.error_message) > MAX_PROCESS_ERROR_CHARACTERS
        ):
            raise ValueError("error_messageは500文字以内で指定してください。")
        if (
            not isinstance(self.duration_seconds, (int, float))
            or isinstance(self.duration_seconds, bool)
            or not isfinite(self.duration_seconds)
            or self.duration_seconds < 0
        ):
            raise ValueError("duration_secondsは0以上の有限数で指定してください。")
