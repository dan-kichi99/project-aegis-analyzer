from dataclasses import dataclass
from enum import Enum

from app.iteration.iteration_action import IterationAction, IterationActionStatus
from app.iteration.iteration_state import AnalysisHypothesis, OpenQuestion

MAX_LOCAL_RESULT_ITEMS = 20
MAX_LOCAL_RESULT_TEXT_CHARACTERS = 500


class LocalAnalysisStatus(str, Enum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class LocalAnalysisResult:
    action_id: str
    analysis_type: str
    status: LocalAnalysisStatus
    summary: str
    hypotheses: tuple[AnalysisHypothesis, ...]
    open_questions: tuple[OpenQuestion, ...]
    flag_candidates: tuple[str, ...]
    next_actions: tuple[IterationAction, ...]
    error_message: str | None

    def __post_init__(self) -> None:
        if not self.action_id.strip():
            raise ValueError("action_idは空にできません。")
        if not self.analysis_type.strip():
            raise ValueError("analysis_typeは空にできません。")
        if len(self.summary) > MAX_LOCAL_RESULT_TEXT_CHARACTERS:
            raise ValueError("summaryは500文字以内で指定してください。")
        if (
            self.error_message is not None
            and len(self.error_message) > MAX_LOCAL_RESULT_TEXT_CHARACTERS
        ):
            raise ValueError("error_messageは500文字以内で指定してください。")
        collections = (
            (self.hypotheses, "hypotheses"),
            (self.open_questions, "open_questions"),
            (self.flag_candidates, "flag_candidates"),
            (self.next_actions, "next_actions"),
        )
        for values, name in collections:
            if len(values) > MAX_LOCAL_RESULT_ITEMS:
                raise ValueError(f"{name}は最大20件です。")
        if any(
            action.status is not IterationActionStatus.PROPOSED
            for action in self.next_actions
        ):
            raise ValueError("next_actionsはPROPOSEDだけを指定してください。")
