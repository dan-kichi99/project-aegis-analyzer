from dataclasses import replace
from datetime import datetime, timezone

from app.agents.agent_aggregate_result import AgentAggregateResult
from app.agents.agent_input import AgentInput
from app.agents.agent_planner import AgentPlanner
from app.agents.agent_result import AgentResult, AgentStatus, AgentType
from app.agents.agent_result_aggregator import AgentResultAggregator
from app.agents.agent_route_result import AgentRouteStatus
from app.agents.agent_router import AgentRouter
from app.client.base_client import BaseAIClient
from app.events.analysis_event import AnalysisEvent, AnalysisEventType
from app.events.event_publisher import EventPublisher

MAX_EXECUTED_AGENTS = 2


class AgentCoordinator:
    """専門Agentの計画、順次実行、結果統合を調整する。"""

    def __init__(
        self,
        planner: AgentPlanner,
        router: AgentRouter,
        aggregator: AgentResultAggregator,
        max_agents: int = MAX_EXECUTED_AGENTS,
        event_publisher: EventPublisher | None = None,
    ) -> None:
        if not 1 <= max_agents <= MAX_EXECUTED_AGENTS:
            raise ValueError("実行可能なAgent数は1件または2件です。")
        self.planner = planner
        self.router = router
        self.aggregator = aggregator
        self.max_agents = max_agents
        self._event_publisher = event_publisher

    def with_ai_clients(
        self,
        clients: dict[AgentType, BaseAIClient],
    ) -> "AgentCoordinator":
        return AgentCoordinator(
            planner=self.planner,
            router=self.router.with_ai_clients(clients),
            aggregator=self.aggregator,
            max_agents=self.max_agents,
            event_publisher=self._event_publisher,
        )

    def analyze(self, agent_input: AgentInput) -> AgentAggregateResult:
        plan = self.planner.plan(agent_input)
        primary = next(
            (item.agent_type.value for item in plan.candidates if item.primary),
            None,
        )
        self._publish(
            AnalysisEventType.AGENT_PLAN_CREATED,
            "専門Agentを選択しました。",
            "agent",
            {"candidate_count": len(plan.candidates), "primary_agent": primary},
        )

        results: list[AgentResult] = []
        executed = 0
        for candidate in plan.candidates:
            if executed >= self.max_agents:
                break
            if not self.router.has_agent(candidate.agent_type):
                continue
            self._publish(
                AnalysisEventType.AGENT_STARTED,
                "専門Agent解析を開始します。",
                "agent",
                {"agent_type": candidate.agent_type.value, "priority": candidate.priority},
            )
            routed_input = replace(agent_input, target_agent=candidate.agent_type)
            route = self.router.route_agent(candidate.agent_type, routed_input)
            executed += 1
            result = route.result
            if result is None:
                result = AgentResult(
                    agent_type=candidate.agent_type,
                    status=AgentStatus.FAILED,
                    summary="Agentの実行中にエラーが発生しました。",
                    answer=None,
                    flag_candidate=None,
                    confidence=None,
                    evidence=(),
                    next_actions=(),
                    error_message=route.error_message,
                )
            results.append(result)
            if route.status is AgentRouteStatus.FAILED:
                self._publish(
                    AnalysisEventType.AGENT_FAILED,
                    "専門Agent解析に失敗しました。",
                    "agent",
                    {
                        "agent_type": candidate.agent_type.value,
                        "error_type": route.error_type,
                    },
                )
            else:
                self._publish(
                    AnalysisEventType.AGENT_COMPLETED,
                    "専門Agent解析が完了しました。",
                    "agent",
                    {
                        "agent_type": candidate.agent_type.value,
                        "status": result.status.value,
                        "has_flag_candidate": result.flag_candidate is not None,
                    },
                )
            if result.flag_candidate is not None:
                break

        aggregate = self.aggregator.aggregate(plan, tuple(results))
        self._publish(
            AnalysisEventType.AGENT_AGGREGATION_COMPLETED,
            "専門Agent結果の統合が完了しました。",
            "agent",
            {
                "completed_count": sum(
                    result.status is AgentStatus.COMPLETED for result in results
                ),
                "flag_candidate_count": len(aggregate.flag_candidates),
                "conflict_count": len(aggregate.conflicts),
            },
        )
        return aggregate

    def _publish(
        self,
        event_type: AnalysisEventType,
        message: str,
        phase: str,
        metadata: dict[str, object],
    ) -> None:
        if self._event_publisher is None:
            return
        self._event_publisher.publish(
            AnalysisEvent(
                event_type=event_type,
                message=message,
                phase=phase,
                timestamp=datetime.now(timezone.utc),
                metadata=metadata,
            )
        )
