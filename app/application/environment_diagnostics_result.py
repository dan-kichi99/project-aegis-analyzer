from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class DiagnosticTargetType(str, Enum):
    PYTHON = "python"
    TKINTER = "tkinter"
    OPENAI_CONFIGURATION = "openai_configuration"
    EXTERNAL_TOOL = "external_tool"


class DiagnosticStatus(str, Enum):
    AVAILABLE = "available"
    NOT_CONFIGURED = "not_configured"
    NOT_FOUND = "not_found"
    INVALID_PATH = "invalid_path"
    SYMLINK_REJECTED = "symlink_rejected"
    NOT_EXECUTABLE = "not_executable"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


@dataclass(slots=True, frozen=True)
class EnvironmentDiagnosticItem:
    target_type: DiagnosticTargetType
    name: str
    status: DiagnosticStatus
    available: bool
    message: str
    executable_path: Path | None = None
    version: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip() or len(self.name) > 100:
            raise ValueError("nameは空でない100文字以内で指定してください。")
        if not self.message.strip() or len(self.message) > 500:
            raise ValueError("messageは空でない500文字以内で指定してください。")
        if self.version is not None and len(self.version) > 200:
            raise ValueError("versionは200文字以内で指定してください。")
        if self.executable_path is not None and not self.executable_path.is_absolute():
            raise ValueError("executable_pathは絶対PathまたはNoneで指定してください。")
        if self.available != (self.status is DiagnosticStatus.AVAILABLE):
            raise ValueError("availableとstatusが一致していません。")


@dataclass(slots=True, frozen=True)
class EnvironmentDiagnosticsResult:
    items: tuple[EnvironmentDiagnosticItem, ...]
    all_required_available: bool
    available_count: int
    unavailable_count: int
    platform_name: str
    python_executable_name: str

    def __post_init__(self) -> None:
        if len(self.items) > 50:
            raise ValueError("itemsは最大50件です。")
        actual_available = sum(item.available for item in self.items)
        if self.available_count != actual_available:
            raise ValueError("available_countがitemsと一致しません。")
        if self.unavailable_count != len(self.items) - actual_available:
            raise ValueError("unavailable_countがitemsと一致しません。")
        if len(self.platform_name) > 100:
            raise ValueError("platform_nameは100文字以内で指定してください。")
        if len(self.python_executable_name) > 200:
            raise ValueError("python_executable_nameは200文字以内で指定してください。")
