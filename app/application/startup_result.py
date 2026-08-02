from dataclasses import dataclass
from enum import Enum

from app.application.environment_diagnostics_result import EnvironmentDiagnosticsResult


class StartupMode(str, Enum):
    CLI = "cli"
    GUI = "gui"
    DIAGNOSTICS = "diagnostics"


class StartupStatus(str, Enum):
    READY = "ready"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class StartupResult:
    mode: StartupMode
    status: StartupStatus
    message: str
    diagnostics: EnvironmentDiagnosticsResult | None
    exit_code: int

    def __post_init__(self) -> None:
        if not self.message.strip() or len(self.message) > 500:
            raise ValueError("message must contain 1 to 500 characters.")
        if isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int):
            raise TypeError("exit_code must be an integer.")
        if self.exit_code < 0:
            raise ValueError("exit_code must be zero or greater.")
