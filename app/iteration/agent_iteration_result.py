from dataclasses import dataclass
from enum import Enum

from app.agents.agent_result import AgentResult, AgentType
from app.agents.agent_route_result import AgentRouteResult

MAX_AGENT_ITERATION_TEXT_CHARACTERS = 500


class AgentIterationStatus(str, Enum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    REPEATED = "repeated"


@dataclass(slots=True, frozen=True)
class AgentIterationResult:
    action_id: str
    agent_type: AgentType
    status: AgentIterationStatus
    route_result: AgentRouteResult
    agent_result: AgentResult | None
    summary: str
    repeated: bool
    error_message: str | None

    def __post_init__(self) -> None:
        if len(self.summary) > MAX_AGENT_ITERATION_TEXT_CHARACTERS:
            raise ValueError("summaryは500文字以内で指定してください。")
        if (
            self.error_message is not None
            and len(self.error_message) > MAX_AGENT_ITERATION_TEXT_CHARACTERS
        ):
            raise ValueError("error_messageは500文字以内で指定してください。")
