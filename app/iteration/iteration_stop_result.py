from dataclasses import dataclass
from enum import Enum

from app.iteration.iteration_state import IterationSession, IterationStopReason

MAX_STOP_MESSAGE_CHARACTERS = 500
MAX_FATAL_ERROR_CHARACTERS = 500


class IterationDecision(str, Enum):
    CONTINUE = "continue"
    COMPLETE = "complete"
    STOP = "stop"
    FAIL = "fail"


@dataclass(slots=True, frozen=True)
class IterationStopContext:
    session: IterationSession
    max_iterations: int
    elapsed_seconds: float | None
    time_budget_seconds: float | None
    ai_calls_used: int | None
    ai_call_budget: int | None
    user_requested_stop: bool
    fatal_error: str | None
    repeated_state: bool | None = None

    def __post_init__(self) -> None:
        if self.max_iterations < 1:
            raise ValueError("max_iterationsは1以上で指定してください。")
        if self.elapsed_seconds is not None and self.elapsed_seconds < 0:
            raise ValueError("elapsed_secondsは0以上で指定してください。")
        if self.time_budget_seconds is not None and self.time_budget_seconds <= 0:
            raise ValueError("time_budget_secondsは0より大きくしてください。")
        if self.ai_calls_used is not None and self.ai_calls_used < 0:
            raise ValueError("ai_calls_usedは0以上で指定してください。")
        if self.ai_call_budget is not None and self.ai_call_budget < 0:
            raise ValueError("ai_call_budgetは0以上で指定してください。")
        if (self.ai_calls_used is None) != (self.ai_call_budget is None):
            raise ValueError("AI使用量と予算は両方指定するか、両方Noneにしてください。")
        if (
            self.fatal_error is not None
            and len(self.fatal_error) > MAX_FATAL_ERROR_CHARACTERS
        ):
            raise ValueError("fatal_errorは500文字以内で指定してください。")


@dataclass(slots=True, frozen=True)
class IterationStopEvaluation:
    decision: IterationDecision
    should_stop: bool
    reason: IterationStopReason | None
    message: str
    matched_conditions: tuple[IterationStopReason, ...]
    requires_user_confirmation: bool

    def __post_init__(self) -> None:
        continuing = self.decision is IterationDecision.CONTINUE
        if continuing == self.should_stop:
            raise ValueError("decisionとshould_stopが一致していません。")
        if continuing and self.reason is not None:
            raise ValueError("CONTINUEではreasonを指定できません。")
        if len(self.message) > MAX_STOP_MESSAGE_CHARACTERS:
            raise ValueError("messageは500文字以内で指定してください。")
