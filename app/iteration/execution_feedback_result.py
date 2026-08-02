from dataclasses import dataclass
from enum import Enum

from app.execution.execution_analysis_result import ExecutionAnalysisResult
from app.iteration.iteration_action import IterationAction, IterationActionStatus
from app.iteration.iteration_state import OpenQuestion

MAX_FEEDBACK_ITEMS = 20
MAX_FEEDBACK_TEXT_CHARACTERS = 500


class ExecutionFeedbackStatus(str, Enum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    REPEATED = "repeated"


@dataclass(slots=True, frozen=True)
class ExecutionFeedbackResult:
    action_id: str
    source_index: int
    status: ExecutionFeedbackStatus
    summary: str
    execution_analysis: ExecutionAnalysisResult
    flag_candidates: tuple[str, ...]
    open_questions: tuple[OpenQuestion, ...]
    next_actions: tuple[IterationAction, ...]
    repeated: bool
    error_message: str | None

    def __post_init__(self) -> None:
        if self.source_index < 0:
            raise ValueError("source_indexは0以上で指定してください。")
        if len(self.summary) > MAX_FEEDBACK_TEXT_CHARACTERS:
            raise ValueError("summaryは500文字以内で指定してください。")
        if (
            self.error_message is not None
            and len(self.error_message) > MAX_FEEDBACK_TEXT_CHARACTERS
        ):
            raise ValueError("error_messageは500文字以内で指定してください。")
        for values, name in (
            (self.flag_candidates, "flag_candidates"),
            (self.open_questions, "open_questions"),
            (self.next_actions, "next_actions"),
        ):
            if len(values) > MAX_FEEDBACK_ITEMS:
                raise ValueError(f"{name}は最大{MAX_FEEDBACK_ITEMS}件です。")
        if any(
            action.status is not IterationActionStatus.PROPOSED
            for action in self.next_actions
        ):
            raise ValueError("next_actionsにはPROPOSED Actionだけを指定できます。")
