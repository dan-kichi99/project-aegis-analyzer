from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType


class AnalysisEventType(str, Enum):
    ANALYSIS_STARTED = "analysis_started"
    FILE_ANALYSIS_STARTED = "file_analysis_started"
    FILE_ANALYSIS_COMPLETED = "file_analysis_completed"
    LOCAL_SOLUTION_FOUND = "local_solution_found"
    AGENT_PLAN_CREATED = "agent_plan_created"
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    AGENT_AGGREGATION_COMPLETED = "agent_aggregation_completed"
    AI_ANALYSIS_STARTED = "ai_analysis_started"
    AI_ANALYSIS_COMPLETED = "ai_analysis_completed"
    ANALYSIS_COMPLETED = "analysis_completed"
    ANALYSIS_FAILED = "analysis_failed"
    ANALYSIS_CANCELLED = "analysis_cancelled"


@dataclass(slots=True, frozen=True)
class AnalysisEvent:
    event_type: AnalysisEventType
    message: str
    phase: str
    timestamp: datetime
    metadata: Mapping[str, object]

    def __post_init__(self) -> None:
        copied_metadata = MappingProxyType(dict(self.metadata))
        object.__setattr__(self, "metadata", copied_metadata)
