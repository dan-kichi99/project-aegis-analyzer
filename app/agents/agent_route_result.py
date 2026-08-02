from dataclasses import dataclass
from enum import Enum

from app.agents.agent_result import AgentResult, AgentType


class AgentRouteStatus(str, Enum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    NO_AGENT = "no_agent"


@dataclass(slots=True, frozen=True)
class AgentRouteResult:
    category: str
    selected_agent: AgentType | None
    status: AgentRouteStatus
    result: AgentResult | None
    error_type: str | None
    error_message: str | None
