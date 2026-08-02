from dataclasses import dataclass
from enum import Enum


class AgentType(str, Enum):
    CRYPTO = "crypto"
    REV = "rev"
    WEB = "web"
    FORENSICS = "forensics"
    MISC = "misc"
    GENERAL = "general"


class AgentStatus(str, Enum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


def _validate_confidence(confidence: int | None) -> None:
    if confidence is not None and not 0 <= confidence <= 100:
        raise ValueError("confidenceは0から100、またはNoneで指定してください。")


@dataclass(slots=True, frozen=True)
class AgentEvidence:
    source: str
    detail: str
    confidence: int | None

    def __post_init__(self) -> None:
        _validate_confidence(self.confidence)


@dataclass(slots=True, frozen=True)
class AgentResult:
    agent_type: AgentType
    status: AgentStatus
    summary: str
    answer: str | None
    flag_candidate: str | None
    confidence: int | None
    evidence: tuple[AgentEvidence, ...]
    next_actions: tuple[str, ...]
    error_message: str | None

    def __post_init__(self) -> None:
        _validate_confidence(self.confidence)

