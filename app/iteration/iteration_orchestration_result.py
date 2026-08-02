from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from pathlib import Path

from app.agents.agent_aggregate_result import AgentAggregateResult
from app.agents.agent_input import AgentInput
from app.challenge.challenge_input import ChallengeInput
from app.execution.execution_analysis_result import ExecutionAnalysisResult
from app.iteration.agent_iteration_coordinator import AgentIterationExecutionResult
from app.iteration.execution_feedback_coordinator import (
    ExecutionFeedbackExecutionResult,
)
from app.iteration.external_tool_iteration_result import (
    ExternalToolIterationExecutionResult,
)
from app.iteration.iteration_action import IterationAction
from app.iteration.iteration_budget import BudgetEvaluation, IterationBudget
from app.iteration.iteration_coordinator import IterationExecutionResult
from app.iteration.iteration_state import IterationSession
from app.iteration.iteration_stop_result import IterationStopEvaluation
from app.iteration.iteration_usage import IterationUsage
from app.judge.judge_result import JudgeResult

MAX_ORCHESTRATION_MESSAGE_CHARACTERS = 500


class IterationOrchestrationStatus(str, Enum):
    CONTINUE = "continue"
    WAITING_APPROVAL = "waiting_approval"
    ACTION_COMPLETED = "action_completed"
    ACTION_SKIPPED = "action_skipped"
    ACTION_FAILED = "action_failed"
    BUDGET_DENIED = "budget_denied"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"
    NO_ACTION = "no_action"


@dataclass(slots=True, frozen=True)
class IterationRunContext:
    session: IterationSession
    usage: IterationUsage
    budget: IterationBudget
    judge_result: JudgeResult | None
    agent_result: AgentAggregateResult | None
    execution_result: ExecutionAnalysisResult | None
    execution_source_index: int | None
    agent_input: AgentInput | None
    updated_at: datetime
    elapsed_seconds: float
    user_requested_stop: bool = False
    fatal_error: str | None = None
    repeated_state: bool | None = None
    challenge: ChallengeInput | None = None
    working_directory: Path | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.elapsed_seconds, (int, float))
            or isinstance(self.elapsed_seconds, bool)
            or not isfinite(self.elapsed_seconds)
            or self.elapsed_seconds < 0
        ):
            raise ValueError("elapsed_secondsは0以上の有限数で指定してください。")
        if self.execution_source_index is not None and (
            not isinstance(self.execution_source_index, int)
            or isinstance(self.execution_source_index, bool)
            or self.execution_source_index < 0
        ):
            raise ValueError("execution_source_indexは0以上、またはNoneです。")
        if self.fatal_error is not None and len(self.fatal_error) > 500:
            raise ValueError("fatal_errorは500文字以内で指定してください。")


@dataclass(slots=True, frozen=True)
class IterationOrchestrationResult:
    status: IterationOrchestrationStatus
    session: IterationSession
    usage: IterationUsage
    planned_actions: tuple[IterationAction, ...]
    selected_action: IterationAction | None
    budget_evaluation: BudgetEvaluation | None
    stop_evaluation: IterationStopEvaluation
    message: str
    local_execution: IterationExecutionResult | None = None
    agent_execution: AgentIterationExecutionResult | None = None
    feedback_execution: ExecutionFeedbackExecutionResult | None = None
    external_tool_execution: ExternalToolIterationExecutionResult | None = None

    def __post_init__(self) -> None:
        if len(self.message) > MAX_ORCHESTRATION_MESSAGE_CHARACTERS:
            raise ValueError("messageは500文字以内で指定してください。")
        if sum(
            value is not None
            for value in (
                self.local_execution,
                self.agent_execution,
                self.feedback_execution,
                self.external_tool_execution,
            )
        ) > 1:
            raise ValueError("Execution結果は同時に1件だけ保持できます。")
