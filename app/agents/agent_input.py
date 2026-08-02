from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from app.agents.agent_result import AgentType
from app.challenge.challenge_input import ChallengeInput


@dataclass(slots=True, frozen=True)
class AgentInput:
    challenge: ChallengeInput
    category: str
    context: str
    local_knowledge: tuple[str, ...]
    metadata: Mapping[str, object] = field(default_factory=dict)
    target_agent: AgentType | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
