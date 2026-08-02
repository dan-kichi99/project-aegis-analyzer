from app.agents.agent import BaseAgent
from app.agents.agent_input import AgentInput
from app.agents.agent_result import AgentStatus, AgentType
from app.agents.agent_route_result import AgentRouteResult, AgentRouteStatus

MAX_ERROR_MESSAGE_CHARACTERS = 500

_CATEGORY_TO_AGENT_TYPE = {
    "crypto": AgentType.CRYPTO,
    "rev": AgentType.REV,
    "web": AgentType.WEB,
    "misc": AgentType.FORENSICS,
    "forensics": AgentType.FORENSICS,
    "unknown": AgentType.GENERAL,
}

_STATUS_TO_ROUTE_STATUS = {
    AgentStatus.COMPLETED: AgentRouteStatus.COMPLETED,
    AgentStatus.SKIPPED: AgentRouteStatus.SKIPPED,
    AgentStatus.FAILED: AgentRouteStatus.FAILED,
}


def category_to_agent_type(category: str) -> AgentType:
    """Analyzerのカテゴリ文字列を専門Agent種別へ変換する。"""
    return _CATEGORY_TO_AGENT_TYPE.get(
        category.strip().casefold(),
        AgentType.GENERAL,
    )


class AgentRouter:
    """カテゴリに対応する登録済み専門Agentを1件だけ実行する。"""

    def __init__(self, agents: tuple[BaseAgent, ...]) -> None:
        registered: dict[AgentType, BaseAgent] = {}
        for agent in agents:
            if agent.agent_type in registered:
                raise ValueError(
                    f"AgentType「{agent.agent_type.value}」が重複しています。"
                )
            registered[agent.agent_type] = agent
        self._agents = tuple(agents)
        self._registered = registered

    @property
    def agents(self) -> tuple[BaseAgent, ...]:
        return self._agents

    def has_agent(self, agent_type: AgentType) -> bool:
        return agent_type in self._registered

    def route(self, agent_input: AgentInput) -> AgentRouteResult:
        category = agent_input.category
        expected_type = category_to_agent_type(category)
        return self.route_agent(expected_type, agent_input)

    def route_agent(
        self,
        agent_type: AgentType,
        agent_input: AgentInput,
    ) -> AgentRouteResult:
        """指定されたAgentTypeを1件だけ実行する。"""
        category = agent_input.category
        expected_type = agent_type
        agent = self._registered.get(expected_type)
        if agent is None:
            return AgentRouteResult(
                category=category,
                selected_agent=expected_type,
                status=AgentRouteStatus.NO_AGENT,
                result=None,
                error_type=None,
                error_message=None,
            )

        try:
            result = agent.analyze(agent_input)
        except Exception as error:  # noqa: BLE001 - Agent失敗をRouter結果へ変換
            return AgentRouteResult(
                category=category,
                selected_agent=expected_type,
                status=AgentRouteStatus.FAILED,
                result=None,
                error_type=type(error).__name__,
                error_message=str(error)[:MAX_ERROR_MESSAGE_CHARACTERS],
            )

        status = _STATUS_TO_ROUTE_STATUS[result.status]
        error_message = result.error_message
        if error_message is not None:
            error_message = error_message[:MAX_ERROR_MESSAGE_CHARACTERS]
        return AgentRouteResult(
            category=category,
            selected_agent=expected_type,
            status=status,
            result=result,
            error_type=None,
            error_message=error_message,
        )
