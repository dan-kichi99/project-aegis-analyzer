from abc import ABC, abstractmethod

from app.agents.agent_input import AgentInput
from app.agents.agent_result import AgentResult, AgentType


class BaseAgent(ABC):
    """専門Agentが実装する同期共通インターフェース。"""

    @property
    @abstractmethod
    def agent_type(self) -> AgentType:
        """このAgentを識別する種別を返す。"""
        raise NotImplementedError

    @abstractmethod
    def analyze(self, agent_input: AgentInput) -> AgentResult:
        """専門分析結果を返す。予期しない例外は呼び出し側へ伝える。"""
        raise NotImplementedError

