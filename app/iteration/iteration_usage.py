from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType

from app.agents.agent_result import AgentType
from app.external_tools.tool import ExternalToolType
from app.iteration.iteration_action import IterationActionType


def _validate_count(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name}は0以上の整数で指定してください。")


@dataclass(slots=True, frozen=True)
class IterationUsage:
    iterations_used: int = 0
    total_actions_used: int = 0
    agent_runs_used: int = 0
    ai_calls_used: int = 0
    local_analyses_used: int = 0
    execution_feedbacks_used: int = 0
    elapsed_seconds: float = 0.0
    action_counts: Mapping[IterationActionType, int] = field(default_factory=dict)
    agent_counts: Mapping[AgentType, int] = field(default_factory=dict)
    external_tool_runs_used: int = 0
    tool_counts: Mapping[ExternalToolType, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "iterations_used",
            "total_actions_used",
            "agent_runs_used",
            "ai_calls_used",
            "local_analyses_used",
            "execution_feedbacks_used",
            "external_tool_runs_used",
        ):
            _validate_count(getattr(self, name), name)
        if (
            not isinstance(self.elapsed_seconds, (int, float))
            or isinstance(self.elapsed_seconds, bool)
            or not isfinite(self.elapsed_seconds)
            or self.elapsed_seconds < 0
        ):
            raise ValueError("elapsed_secondsは0以上の有限数で指定してください。")
        actions = dict(self.action_counts)
        agents = dict(self.agent_counts)
        tools = dict(self.tool_counts)
        self._validate_mapping(actions, IterationActionType, "action_counts")
        self._validate_mapping(agents, AgentType, "agent_counts")
        self._validate_mapping(tools, ExternalToolType, "tool_counts")
        object.__setattr__(self, "action_counts", MappingProxyType(actions))
        object.__setattr__(self, "agent_counts", MappingProxyType(agents))
        object.__setattr__(self, "tool_counts", MappingProxyType(tools))

    def _validate_mapping(self, values: dict, key_type: type, name: str) -> None:
        for key, value in values.items():
            if not isinstance(key, key_type):
                raise ValueError(  # noqa: TRY004 - DTO入力違反はValueErrorへ統一
                    f"{name}に未定義のキーがあります。"
                )
            _validate_count(value, name)
