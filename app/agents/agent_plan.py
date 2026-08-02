from dataclasses import dataclass

from app.agents.agent_result import AgentType


@dataclass(slots=True, frozen=True)
class AgentCandidate:
    agent_type: AgentType
    priority: int
    reason: str
    primary: bool


@dataclass(slots=True, frozen=True)
class AgentExecutionPlan:
    category: str
    candidates: tuple[AgentCandidate, ...]

    def __post_init__(self) -> None:
        if len(self.candidates) > 3:
            raise ValueError("Agent候補は最大3件です。")
        agent_types = tuple(candidate.agent_type for candidate in self.candidates)
        if len(agent_types) != len(set(agent_types)):
            raise ValueError("同じAgentTypeを重複して計画できません。")
        if sum(candidate.primary for candidate in self.candidates) > 1:
            raise ValueError("主担当Agentは最大1件です。")
