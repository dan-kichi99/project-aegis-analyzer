from dataclasses import dataclass
from enum import Enum


class ApplicationStatus(str, Enum):
    IDLE = "idle"
    ANALYZING = "analyzing"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class ProgressViewModel:
    status: ApplicationStatus
    phase: str
    message: str
    progress_percent: int | None
    current_agent: str | None
    error_type: str | None

    def __post_init__(self) -> None:
        if len(self.phase) > 100 or len(self.message) > 500:
            raise ValueError("phaseまたはmessageが表示上限を超えています。")
        if self.progress_percent is not None and not 0 <= self.progress_percent <= 100:
            raise ValueError("progress_percentは0から100またはNoneです。")


@dataclass(slots=True, frozen=True)
class ResultViewModel:
    solved: bool
    category: str
    answer: str
    flag_candidate: str | None
    confidence: int | None
    reason: str
    next_actions: tuple[str, ...]
    warning: str | None

    def __post_init__(self) -> None:
        if len(self.answer) > 20_000 or len(self.reason) > 2_000:
            raise ValueError("結果表示が文字数上限を超えています。")
        if len(self.next_actions) > 20 or any(
            len(action) > 500 for action in self.next_actions
        ):
            raise ValueError("next_actionsが表示上限を超えています。")


@dataclass(slots=True, frozen=True)
class AgentViewModel:
    primary_agent: str | None
    executed_agents: tuple[str, ...]
    status: str
    confidence: int | None
    evidence: tuple[str, ...]
    flag_candidates: tuple[str, ...]
    conflicts: tuple[str, ...]
    used_fallback: bool

    def __post_init__(self) -> None:
        if len(self.evidence) > 30 or any(len(item) > 1_000 for item in self.evidence):
            raise ValueError("evidenceが表示上限を超えています。")
        if len(self.flag_candidates) > 20 or len(self.conflicts) > 20:
            raise ValueError("Agent候補情報が表示上限を超えています。")


@dataclass(slots=True, frozen=True)
class ActionViewModel:
    action_id: str
    action_type: str
    status: str
    priority: int
    description: str
    requires_user_approval: bool


@dataclass(slots=True, frozen=True)
class IterationViewModel:
    session_id: str
    status: str
    current_iteration: int
    pending_actions: tuple[ActionViewModel, ...]
    hypotheses: tuple[str, ...]
    open_questions: tuple[str, ...]
    flag_candidates: tuple[str, ...]
    stop_reason: str | None


@dataclass(slots=True, frozen=True)
class BudgetViewModel:
    iterations_used: int
    iterations_max: int
    actions_used: int
    actions_max: int
    agent_runs_used: int
    agent_runs_max: int
    ai_calls_used: int
    ai_calls_max: int
    local_analyses_used: int
    local_analyses_max: int
    feedbacks_used: int
    feedbacks_max: int
    external_tool_runs_used: int
    external_tool_runs_max: int
    elapsed_seconds: float
    elapsed_seconds_max: float


@dataclass(slots=True, frozen=True)
class ExternalToolViewModel:
    tool_type: str
    status: str
    target_name: str
    summary: str
    exit_code: int | None
    evidence: tuple[str, ...]
    repeated: bool
    error_message: str | None


@dataclass(slots=True, frozen=True)
class ApplicationState:
    progress: ProgressViewModel
    result: ResultViewModel | None
    agent: AgentViewModel | None
    iteration: IterationViewModel | None
    budget: BudgetViewModel | None
    external_tools: tuple[ExternalToolViewModel, ...]
