from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from app.agents.agent_result import AgentType

MAX_ACTION_TEXT_CHARACTERS = 1_000
MAX_ACTION_METADATA_KEYS = 50


class IterationActionType(str, Enum):
    RUN_AGENT = "run_agent"
    RUN_LOCAL_ANALYSIS = "run_local_analysis"
    REVIEW_CODE = "review_code"
    EXECUTE_APPROVED_CODE = "execute_approved_code"
    ANALYZE_EXECUTION_OUTPUT = "analyze_execution_output"
    REQUEST_USER_INPUT = "request_user_input"
    MANUAL_REVIEW = "manual_review"
    STOP = "stop"
    RUN_EXTERNAL_TOOL = "run_external_tool"


class IterationActionStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(slots=True, frozen=True)
class IterationAction:
    action_id: str
    action_type: IterationActionType
    status: IterationActionStatus
    title: str
    description: str
    priority: int
    reason: str
    target_agent: AgentType | None
    requires_user_approval: bool
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.action_id.strip():
            raise ValueError("action_idは空にできません。")
        if not self.title.strip():
            raise ValueError("titleは空にできません。")
        if not 0 <= self.priority <= 100:
            raise ValueError("priorityは0から100で指定してください。")
        if len(self.description) > MAX_ACTION_TEXT_CHARACTERS:
            raise ValueError("descriptionは1000文字以内で指定してください。")
        if len(self.reason) > MAX_ACTION_TEXT_CHARACTERS:
            raise ValueError("reasonは1000文字以内で指定してください。")
        copied = dict(self.metadata)
        if len(copied) > MAX_ACTION_METADATA_KEYS:
            raise ValueError("metadataは最大50件です。")
        object.__setattr__(self, "metadata", MappingProxyType(copied))
