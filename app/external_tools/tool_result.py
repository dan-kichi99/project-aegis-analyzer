from dataclasses import dataclass
from enum import Enum

from app.external_tools.tool import ExternalToolType

MAX_TOOL_RESULT_TEXT_CHARACTERS = 500
MAX_TOOL_OUTPUT_CHARACTERS = 65_536
MAX_TOOL_EVIDENCE_ITEMS = 50


class ExternalToolStatus(str, Enum):
    NOT_RUN = "not_run"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(slots=True, frozen=True)
class ToolEvidence:
    source: str
    detail: str
    confidence: int | None

    def __post_init__(self) -> None:
        if self.confidence is not None and not 0 <= self.confidence <= 100:
            raise ValueError("confidenceは0から100、またはNoneで指定してください。")
        if len(self.detail) > MAX_TOOL_RESULT_TEXT_CHARACTERS:
            raise ValueError("detailは500文字以内で指定してください。")


@dataclass(slots=True, frozen=True)
class ToolResult:
    tool_type: ExternalToolType
    status: ExternalToolStatus
    summary: str
    stdout: str
    stderr: str
    exit_code: int | None
    evidence: tuple[ToolEvidence, ...]
    error_message: str | None

    def __post_init__(self) -> None:
        if len(self.summary) > MAX_TOOL_RESULT_TEXT_CHARACTERS:
            raise ValueError("summaryは500文字以内で指定してください。")
        if len(self.stdout) > MAX_TOOL_OUTPUT_CHARACTERS:
            raise ValueError("stdoutは65536文字以内で指定してください。")
        if len(self.stderr) > MAX_TOOL_OUTPUT_CHARACTERS:
            raise ValueError("stderrは65536文字以内で指定してください。")
        if (
            self.error_message is not None
            and len(self.error_message) > MAX_TOOL_RESULT_TEXT_CHARACTERS
        ):
            raise ValueError("error_messageは500文字以内で指定してください。")
        if len(self.evidence) > MAX_TOOL_EVIDENCE_ITEMS:
            raise ValueError("evidenceは最大50件です。")
