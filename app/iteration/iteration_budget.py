from dataclasses import dataclass
from enum import Enum
from math import isfinite

from app.agents.agent_result import AgentType
from app.iteration.iteration_usage import IterationUsage

MAX_BUDGET_MESSAGE_CHARACTERS = 500


def _require_integer(value: int, name: str, minimum: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{name}は{minimum}以上の整数で指定してください。")


@dataclass(slots=True, frozen=True)
class IterationBudget:
    max_iterations: int = 10
    max_total_actions: int = 20
    max_agent_runs: int = 4
    max_ai_calls: int = 4
    max_local_analyses: int = 10
    max_execution_feedbacks: int = 10
    max_elapsed_seconds: float = 300.0
    max_runs_per_agent: int = 2

    def __post_init__(self) -> None:
        _require_integer(self.max_iterations, "max_iterations", 1)
        _require_integer(self.max_total_actions, "max_total_actions", 1)
        _require_integer(self.max_agent_runs, "max_agent_runs", 0)
        _require_integer(self.max_ai_calls, "max_ai_calls", 0)
        _require_integer(self.max_local_analyses, "max_local_analyses", 0)
        _require_integer(
            self.max_execution_feedbacks, "max_execution_feedbacks", 0
        )
        if (
            not isinstance(self.max_elapsed_seconds, (int, float))
            or isinstance(self.max_elapsed_seconds, bool)
            or not isfinite(self.max_elapsed_seconds)
            or self.max_elapsed_seconds <= 0
        ):
            raise ValueError("max_elapsed_secondsは0より大きい有限数で指定してください。")
        _require_integer(self.max_runs_per_agent, "max_runs_per_agent", 1)


class BudgetDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


class BudgetDenialReason(str, Enum):
    SESSION_NOT_ACTIVE = "session_not_active"
    ACTION_NOT_APPROVED = "action_not_approved"
    TIME_LIMIT_REACHED = "time_limit_reached"
    ITERATION_LIMIT_REACHED = "iteration_limit_reached"
    TOTAL_ACTION_LIMIT_REACHED = "total_action_limit_reached"
    AI_CALL_LIMIT_REACHED = "ai_call_limit_reached"
    AGENT_RUN_LIMIT_REACHED = "agent_run_limit_reached"
    AGENT_TYPE_LIMIT_REACHED = "agent_type_limit_reached"
    LOCAL_ANALYSIS_LIMIT_REACHED = "local_analysis_limit_reached"
    EXECUTION_FEEDBACK_LIMIT_REACHED = "execution_feedback_limit_reached"
    UNSUPPORTED_ACTION = "unsupported_action"
    INVALID_COST = "invalid_cost"


@dataclass(slots=True, frozen=True)
class BudgetEvaluation:
    decision: BudgetDecision
    allowed: bool
    primary_reason: BudgetDenialReason | None
    matched_reasons: tuple[BudgetDenialReason, ...]
    message: str
    projected_usage: IterationUsage | None

    def __post_init__(self) -> None:
        if len(self.message) > MAX_BUDGET_MESSAGE_CHARACTERS:
            raise ValueError("messageは500文字以内で指定してください。")
        if self.decision is BudgetDecision.ALLOW:
            if not self.allowed or self.primary_reason is not None:
                raise ValueError("ALLOWではallowed=True、primary_reason=Noneが必要です。")
        elif self.allowed or self.primary_reason is None:
            raise ValueError("DENYではallowed=False、primary_reasonが必要です。")
        if self.primary_reason is not None and (
            not self.matched_reasons
            or self.matched_reasons[0] is not self.primary_reason
        ):
            raise ValueError("primary_reasonはmatched_reasonsの先頭にしてください。")


@dataclass(slots=True, frozen=True)
class IterationActionCost:
    actions: int
    iterations: int
    agent_runs: int
    ai_calls: int
    local_analyses: int
    execution_feedbacks: int
    target_agent: AgentType | None

    def __post_init__(self) -> None:
        for name in (
            "actions",
            "iterations",
            "agent_runs",
            "ai_calls",
            "local_analyses",
            "execution_feedbacks",
        ):
            _require_integer(getattr(self, name), name, 0)
        if self.target_agent is not None and not isinstance(self.target_agent, AgentType):
            raise ValueError("target_agentはAgentTypeまたはNoneで指定してください。")
