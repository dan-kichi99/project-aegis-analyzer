from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.external_tools.tool import ExternalToolType
from app.external_tools.tool_result import ToolResult
from app.iteration.iteration_action import IterationAction
from app.iteration.iteration_state import IterationSession, IterationStep

MAX_EXTERNAL_TOOL_ITERATION_TEXT_CHARACTERS = 500


class ExternalToolIterationStatus(str, Enum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    REPEATED = "repeated"


@dataclass(slots=True, frozen=True)
class ExternalToolIterationResult:
    action_id: str
    tool_type: ExternalToolType
    target_path: Path
    status: ExternalToolIterationStatus
    tool_result: ToolResult
    summary: str
    repeated: bool
    error_message: str | None

    def __post_init__(self) -> None:
        if len(self.summary) > MAX_EXTERNAL_TOOL_ITERATION_TEXT_CHARACTERS:
            raise ValueError("summaryは500文字以内で指定してください。")
        if (
            self.error_message is not None
            and len(self.error_message) > MAX_EXTERNAL_TOOL_ITERATION_TEXT_CHARACTERS
        ):
            raise ValueError("error_messageは500文字以内で指定してください。")


@dataclass(slots=True, frozen=True)
class ExternalToolIterationExecutionResult:
    session: IterationSession
    action: IterationAction
    tool_iteration_result: ExternalToolIterationResult
    step: IterationStep
