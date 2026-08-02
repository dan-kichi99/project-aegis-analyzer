from dataclasses import dataclass, replace
from datetime import datetime

from app.agents.agent_aggregate_result import AgentAggregateResult
from app.agents.agent_input import AgentInput
from app.agents.agent_result import AgentEvidence, AgentResult, AgentStatus, AgentType
from app.agents.agent_route_result import AgentRouteResult, AgentRouteStatus
from app.agents.agent_router import AgentRouter
from app.iteration.agent_iteration_result import (
    MAX_AGENT_ITERATION_TEXT_CHARACTERS,
    AgentIterationResult,
    AgentIterationStatus,
)
from app.iteration.iteration_action import (
    IterationAction,
    IterationActionStatus,
    IterationActionType,
)
from app.iteration.iteration_state import (
    IterationSession,
    IterationSessionStatus,
    IterationStep,
    IterationStepStatus,
)
from app.iteration.iteration_state_manager import IterationStateManager


@dataclass(slots=True, frozen=True)
class AgentIterationRequest:
    session: IterationSession
    action: IterationAction
    agent_input: AgentInput


@dataclass(slots=True, frozen=True)
class AgentIterationExecutionResult:
    session: IterationSession
    action: IterationAction
    agent_iteration_result: AgentIterationResult
    step: IterationStep


class AgentIterationCoordinator:
    """承認済みRUN_AGENT Actionを単一Agentへ一度だけ委譲する。"""

    def __init__(
        self,
        *,
        state_manager: IterationStateManager,
        router: AgentRouter,
        max_runs_per_agent: int = 2,
    ) -> None:
        if max_runs_per_agent < 1:
            raise ValueError("max_runs_per_agentは1以上で指定してください。")
        self.state_manager = state_manager
        self.router = router
        self.max_runs_per_agent = max_runs_per_agent

    def execute_action(
        self,
        *,
        session: IterationSession,
        action_id: str,
        agent_input: AgentInput,
        updated_at: datetime,
    ) -> AgentIterationExecutionResult:
        action, agent_type = self._validate(session, action_id, updated_at)
        if self._run_count(session, agent_type) >= self.max_runs_per_agent:
            raise ValueError(f"Agent「{agent_type.value}」は実行回数上限に達しています。")

        routed_input = replace(agent_input, target_agent=agent_type)
        try:
            route = self.router.route_agent(agent_type, routed_input)
        except Exception as error:  # noqa: BLE001 - Router例外を履歴DTOへ変換
            detail = f"{type(error).__name__}: {error}"[
                :MAX_AGENT_ITERATION_TEXT_CHARACTERS
            ]
            route = AgentRouteResult(
                category=agent_input.category,
                selected_agent=agent_type,
                status=AgentRouteStatus.FAILED,
                result=None,
                error_type=type(error).__name__,
                error_message=detail,
            )

        agent_result = route.result or self._failed_result(agent_type, route)
        status = self._status(route.status)
        repeated = self._is_repeated(session, agent_result)
        if repeated:
            status = AgentIterationStatus.REPEATED
        summary = (
            "過去と同一の専門Agent結果を検出しました。"
            if repeated
            else agent_result.summary
        )[:MAX_AGENT_ITERATION_TEXT_CHARACTERS]
        error_message = (
            (agent_result.error_message or route.error_message)
            if status is AgentIterationStatus.FAILED
            else None
        )
        if error_message is not None:
            error_message = error_message[:MAX_AGENT_ITERATION_TEXT_CHARACTERS]
        iteration_result = AgentIterationResult(
            action_id=action.action_id,
            agent_type=agent_type,
            status=status,
            route_result=route,
            agent_result=agent_result,
            summary=summary,
            repeated=repeated,
            error_message=error_message,
        )
        aggregate = self._aggregate(agent_input.category, agent_result)
        step = self._step(session, action, iteration_result, aggregate)
        appended = self.state_manager.append_step(session, step, updated_at)
        final_status = {
            AgentIterationStatus.COMPLETED: IterationActionStatus.COMPLETED,
            AgentIterationStatus.SKIPPED: IterationActionStatus.SKIPPED,
            AgentIterationStatus.REPEATED: IterationActionStatus.SKIPPED,
            AgentIterationStatus.FAILED: IterationActionStatus.FAILED,
        }[status]
        finalized = self.state_manager.complete_action(
            appended, action.action_id, final_status, updated_at
        )
        return AgentIterationExecutionResult(finalized, action, iteration_result, step)

    def _validate(
        self,
        session: IterationSession,
        action_id: str,
        updated_at: datetime,
    ) -> tuple[IterationAction, AgentType]:
        if session.status is not IterationSessionStatus.ACTIVE:
            raise ValueError("ACTIVE Sessionだけを処理できます。")
        if not action_id.strip():
            raise ValueError("action_idは空にできません。")
        if updated_at < session.updated_at:
            raise ValueError("updated_atを過去へ戻すことはできません。")
        matches = tuple(
            action for action in session.pending_actions if action.action_id == action_id
        )
        if len(matches) != 1:
            raise ValueError("対象Actionはpending_actionsに1件だけ存在する必要があります。")
        action = matches[0]
        if action.status is not IterationActionStatus.APPROVED:
            raise ValueError("APPROVED Actionだけを実行できます。")
        if action.action_type is not IterationActionType.RUN_AGENT:
            raise ValueError("RUN_AGENT Actionだけを実行できます。")
        raw_type = action.metadata.get("agent_type")
        try:
            agent_type = raw_type if isinstance(raw_type, AgentType) else AgentType(raw_type)
        except (TypeError, ValueError) as error:
            raise ValueError("metadataに有効なagent_typeが必要です。") from error
        if action.target_agent is None:
            raise ValueError("target_agentが必要です。")
        if action.target_agent is not agent_type:
            raise ValueError("metadata agent_typeとtarget_agentが一致しません。")
        if not self.router.has_agent(agent_type):
            raise ValueError(f"Agent「{agent_type.value}」は登録されていません。")
        return action, agent_type

    def _run_count(self, session: IterationSession, agent_type: AgentType) -> int:
        return sum(
            result.agent_type is agent_type
            for step in session.steps
            if step.agent_result is not None
            for result in step.agent_result.results
        )

    def _is_repeated(self, session: IterationSession, result: AgentResult) -> bool:
        fingerprint = self._fingerprint(result)
        return any(
            self._fingerprint(previous) == fingerprint
            for step in session.steps
            if step.agent_result is not None
            for previous in step.agent_result.results
            if previous.agent_type is result.agent_type
        )

    def _fingerprint(self, result: AgentResult) -> tuple[object, ...]:
        return (
            result.agent_type,
            result.status,
            result.summary,
            result.answer,
            result.flag_candidate,
            result.confidence,
            result.evidence,
            result.next_actions,
            result.error_message,
        )

    def _status(self, route_status: AgentRouteStatus) -> AgentIterationStatus:
        return {
            AgentRouteStatus.COMPLETED: AgentIterationStatus.COMPLETED,
            AgentRouteStatus.SKIPPED: AgentIterationStatus.SKIPPED,
            AgentRouteStatus.FAILED: AgentIterationStatus.FAILED,
            AgentRouteStatus.NO_AGENT: AgentIterationStatus.FAILED,
        }[route_status]

    def _failed_result(
        self,
        agent_type: AgentType,
        route: AgentRouteResult,
    ) -> AgentResult:
        error_message = route.error_message
        if error_message is not None:
            error_message = error_message[:MAX_AGENT_ITERATION_TEXT_CHARACTERS]
        return AgentResult(
            agent_type=agent_type,
            status=AgentStatus.FAILED,
            summary="反復Agent解析中にエラーが発生しました。",
            answer=None,
            flag_candidate=None,
            confidence=None,
            evidence=(),
            next_actions=(),
            error_message=error_message,
        )

    def _aggregate(
        self,
        category: str,
        result: AgentResult,
    ) -> AgentAggregateResult:
        evidence = tuple(
            AgentEvidence(
                source=f"[{result.agent_type.value}] {item.source}",
                detail=item.detail[:500],
                confidence=item.confidence,
            )
            for item in result.evidence[:30]
        )
        flag_candidates = (
            (result.flag_candidate,) if result.flag_candidate is not None else ()
        )
        return AgentAggregateResult(
            results=(result,),
            primary_result=result,
            status=result.status,
            summary=f"{result.agent_type.value} Agentの反復解析結果を記録しました。",
            flag_candidates=flag_candidates,
            primary_flag=result.flag_candidate,
            confidence=result.confidence,
            evidence=evidence,
            next_actions=result.next_actions[:15],
            conflicts=(),
            used_fallback=False,
            category=category,
        )

    def _step(
        self,
        session: IterationSession,
        action: IterationAction,
        result: AgentIterationResult,
        aggregate: AgentAggregateResult,
    ) -> IterationStep:
        step_status = {
            AgentIterationStatus.COMPLETED: IterationStepStatus.COMPLETED,
            AgentIterationStatus.SKIPPED: IterationStepStatus.SKIPPED,
            AgentIterationStatus.REPEATED: IterationStepStatus.SKIPPED,
            AgentIterationStatus.FAILED: IterationStepStatus.FAILED,
        }[result.status]
        completed_ids = (
            ()
            if result.status is AgentIterationStatus.FAILED
            else (action.action_id,)
        )
        return IterationStep(
            iteration_number=session.current_iteration + 1,
            status=step_status,
            summary=result.summary,
            agent_result=aggregate,
            execution_result=None,
            hypotheses=(),
            open_questions=(),
            proposed_actions=(),
            completed_action_ids=completed_ids,
            error_message=result.error_message,
        )
