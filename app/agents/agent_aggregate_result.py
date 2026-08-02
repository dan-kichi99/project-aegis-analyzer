from dataclasses import dataclass

from app.agents.agent_result import AgentEvidence, AgentResult, AgentStatus, AgentType


@dataclass(slots=True, frozen=True)
class AgentConflict:
    field: str
    values: tuple[str, ...]
    agents: tuple[AgentType, ...]


@dataclass(slots=True, frozen=True)
class AgentAggregateResult:
    results: tuple[AgentResult, ...]
    primary_result: AgentResult | None
    status: AgentStatus
    summary: str
    flag_candidates: tuple[str, ...]
    primary_flag: str | None
    confidence: int | None
    evidence: tuple[AgentEvidence, ...]
    next_actions: tuple[str, ...]
    conflicts: tuple[AgentConflict, ...]
