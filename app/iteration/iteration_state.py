from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from app.agents.agent_aggregate_result import AgentAggregateResult
from app.execution.execution_analysis_result import ExecutionAnalysisResult
from app.iteration.iteration_action import IterationAction, IterationActionStatus

if TYPE_CHECKING:
    from app.iteration.external_tool_iteration_result import ExternalToolIterationResult

MAX_STEPS = 100
MAX_HYPOTHESES = 100
MAX_OPEN_QUESTIONS = 100
MAX_PENDING_ACTIONS = 100
MAX_FLAG_CANDIDATES = 50
MAX_STEP_ACTIONS = 20
MAX_SUMMARY_CHARACTERS = 500
MAX_STATE_TEXT_CHARACTERS = 1_000
MAX_ERROR_MESSAGE_CHARACTERS = 500


class IterationSessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class IterationStepStatus(str, Enum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class IterationStopReason(str, Enum):
    FLAG_CANDIDATE_FOUND = "flag_candidate_found"
    NO_ACTIONS_AVAILABLE = "no_actions_available"
    MAX_ITERATIONS_REACHED = "max_iterations_reached"
    TIME_BUDGET_EXCEEDED = "time_budget_exceeded"
    AI_BUDGET_EXCEEDED = "ai_budget_exceeded"
    USER_STOPPED = "user_stopped"
    REPEATED_STATE = "repeated_state"
    ERROR = "error"


class HypothesisStatus(str, Enum):
    OPEN = "open"
    SUPPORTED = "supported"
    REJECTED = "rejected"
    RESOLVED = "resolved"


class OpenQuestionStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    BLOCKED = "blocked"


@dataclass(slots=True, frozen=True)
class AnalysisHypothesis:
    hypothesis_id: str
    statement: str
    source: str
    confidence: int | None
    status: HypothesisStatus
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.hypothesis_id.strip():
            raise ValueError("hypothesis_idは空にできません。")
        if not self.statement.strip():
            raise ValueError("statementは空にできません。")
        if len(self.statement) > MAX_STATE_TEXT_CHARACTERS:
            raise ValueError("statementは1000文字以内で指定してください。")
        if self.confidence is not None and not 0 <= self.confidence <= 100:
            raise ValueError("confidenceは0から100、またはNoneで指定してください。")


@dataclass(slots=True, frozen=True)
class OpenQuestion:
    question_id: str
    question: str
    source: str
    status: OpenQuestionStatus
    resolution: str | None

    def __post_init__(self) -> None:
        if not self.question_id.strip():
            raise ValueError("question_idは空にできません。")
        if not self.question.strip():
            raise ValueError("questionは空にできません。")
        if len(self.question) > MAX_STATE_TEXT_CHARACTERS:
            raise ValueError("questionは1000文字以内で指定してください。")
        if self.status is OpenQuestionStatus.RESOLVED and not (
            self.resolution and self.resolution.strip()
        ):
            raise ValueError("RESOLVEDにはresolutionが必要です。")


@dataclass(slots=True, frozen=True)
class IterationStep:
    iteration_number: int
    status: IterationStepStatus
    summary: str
    agent_result: AgentAggregateResult | None
    execution_result: ExecutionAnalysisResult | None
    hypotheses: tuple[AnalysisHypothesis, ...]
    open_questions: tuple[OpenQuestion, ...]
    proposed_actions: tuple[IterationAction, ...]
    completed_action_ids: tuple[str, ...]
    error_message: str | None
    feedback_source_index: int | None = None
    external_tool_result: ExternalToolIterationResult | None = None

    def __post_init__(self) -> None:
        if self.iteration_number < 1:
            raise ValueError("iteration_numberは1以上で指定してください。")
        if len(self.summary) > MAX_SUMMARY_CHARACTERS:
            raise ValueError("summaryは500文字以内で指定してください。")
        if len(self.proposed_actions) > MAX_STEP_ACTIONS:
            raise ValueError("1ステップのproposed_actionsは最大20件です。")
        if (
            self.error_message is not None
            and len(self.error_message) > MAX_ERROR_MESSAGE_CHARACTERS
        ):
            raise ValueError("error_messageは500文字以内で指定してください。")
        if self.feedback_source_index is not None and self.feedback_source_index < 0:
            raise ValueError("feedback_source_indexは0以上、またはNoneで指定してください。")


@dataclass(slots=True, frozen=True)
class IterationSession:
    session_id: str
    status: IterationSessionStatus
    current_iteration: int
    steps: tuple[IterationStep, ...]
    hypotheses: tuple[AnalysisHypothesis, ...]
    open_questions: tuple[OpenQuestion, ...]
    pending_actions: tuple[IterationAction, ...]
    flag_candidates: tuple[str, ...]
    primary_flag: str | None
    stop_reason: IterationStopReason | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_idは空にできません。")
        if self.current_iteration < 0:
            raise ValueError("current_iterationは0以上で指定してください。")
        expected_numbers = tuple(range(1, len(self.steps) + 1))
        if tuple(step.iteration_number for step in self.steps) != expected_numbers:
            raise ValueError("stepsのiteration_numberが連続していません。")
        if self.current_iteration != len(self.steps):
            raise ValueError("current_iterationとstepsが一致しません。")
        if self.status is IterationSessionStatus.ACTIVE and self.stop_reason is not None:
            raise ValueError("ACTIVEではstop_reasonを指定できません。")
        if self.created_at > self.updated_at:
            raise ValueError("created_atはupdated_at以前である必要があります。")
        self._validate_limits()
        unique_flags = tuple(dict.fromkeys(self.flag_candidates))
        object.__setattr__(self, "flag_candidates", unique_flags)
        if self.primary_flag is not None and self.primary_flag not in unique_flags:
            raise ValueError("primary_flagはflag_candidatesに含めてください。")

    def _validate_limits(self) -> None:
        limits = (
            (len(self.steps), MAX_STEPS, "steps"),
            (len(self.hypotheses), MAX_HYPOTHESES, "hypotheses"),
            (len(self.open_questions), MAX_OPEN_QUESTIONS, "open_questions"),
            (len(self.pending_actions), MAX_PENDING_ACTIONS, "pending_actions"),
            (len(set(self.flag_candidates)), MAX_FLAG_CANDIDATES, "flag_candidates"),
        )
        for count, maximum, name in limits:
            if count > maximum:
                raise ValueError(f"{name}は最大{maximum}件です。")
        if any(
            action.status
            not in {IterationActionStatus.PROPOSED, IterationActionStatus.APPROVED}
            for action in self.pending_actions
        ):
            raise ValueError("pending_actionsにはPROPOSEDまたはAPPROVEDだけを保持できます。")
