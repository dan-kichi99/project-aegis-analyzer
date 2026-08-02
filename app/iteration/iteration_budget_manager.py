from dataclasses import replace
from math import isfinite

from app.agents.agent_result import AgentType
from app.iteration.iteration_action import (
    IterationAction,
    IterationActionStatus,
    IterationActionType,
)
from app.iteration.iteration_budget import (
    BudgetDecision,
    BudgetDenialReason,
    BudgetEvaluation,
    IterationActionCost,
    IterationBudget,
)
from app.iteration.iteration_state import IterationSession, IterationSessionStatus
from app.iteration.iteration_usage import IterationUsage


class UnsupportedActionError(ValueError):
    pass


class InvalidActionCostError(ValueError):
    pass


class IterationActionCostResolver:
    def resolve(self, action: IterationAction) -> IterationActionCost:
        if action.action_type is IterationActionType.RUN_LOCAL_ANALYSIS:
            return IterationActionCost(1, 1, 0, 0, 1, 0, None)
        if action.action_type is IterationActionType.ANALYZE_EXECUTION_OUTPUT:
            return IterationActionCost(1, 1, 0, 0, 0, 1, None)
        if action.action_type is IterationActionType.RUN_AGENT:
            agent_type = self._agent_type(action)
            return IterationActionCost(1, 1, 1, 1, 0, 0, agent_type)
        raise UnsupportedActionError(
            f"Action「{action.action_type.value}」は予算評価対象外です。"
        )

    def _agent_type(self, action: IterationAction) -> AgentType:
        if action.target_agent is None:
            raise InvalidActionCostError("RUN_AGENTにはtarget_agentが必要です。")
        raw_type = action.metadata.get("agent_type")
        try:
            agent_type = raw_type if isinstance(raw_type, AgentType) else AgentType(raw_type)
        except (TypeError, ValueError) as error:
            raise InvalidActionCostError(
                "RUN_AGENT metadataに有効なagent_typeが必要です。"
            ) from error
        if agent_type is not action.target_agent:
            raise InvalidActionCostError(
                "RUN_AGENTのtarget_agentとmetadata agent_typeが一致しません。"
            )
        return agent_type


class IterationBudgetManager:
    """Actionを実行せず、予算評価とUsageの不変更新だけを行う。"""

    def __init__(self) -> None:
        self.cost_resolver = IterationActionCostResolver()

    def create_usage(self) -> IterationUsage:
        return IterationUsage()

    def evaluate_action(
        self,
        *,
        session: IterationSession,
        action: IterationAction,
        budget: IterationBudget,
        usage: IterationUsage,
        elapsed_seconds: float,
    ) -> BudgetEvaluation:
        self._validate_elapsed(usage, elapsed_seconds)
        reasons: list[BudgetDenialReason] = []
        if session.status is not IterationSessionStatus.ACTIVE:
            reasons.append(BudgetDenialReason.SESSION_NOT_ACTIVE)
        if action.status is not IterationActionStatus.APPROVED:
            reasons.append(BudgetDenialReason.ACTION_NOT_APPROVED)
        if elapsed_seconds >= budget.max_elapsed_seconds:
            reasons.append(BudgetDenialReason.TIME_LIMIT_REACHED)

        cost = None
        cost_reason = None
        try:
            cost = self.cost_resolver.resolve(action)
        except UnsupportedActionError:
            cost_reason = BudgetDenialReason.UNSUPPORTED_ACTION
        except InvalidActionCostError:
            cost_reason = BudgetDenialReason.INVALID_COST

        projected = None
        if cost is not None:
            projected = self.consume(
                usage=usage,
                action=action,
                cost=cost,
                elapsed_seconds=elapsed_seconds,
            )
            if projected.iterations_used > budget.max_iterations:
                reasons.append(BudgetDenialReason.ITERATION_LIMIT_REACHED)
            if projected.total_actions_used > budget.max_total_actions:
                reasons.append(BudgetDenialReason.TOTAL_ACTION_LIMIT_REACHED)
            if projected.ai_calls_used > budget.max_ai_calls:
                reasons.append(BudgetDenialReason.AI_CALL_LIMIT_REACHED)
            if projected.agent_runs_used > budget.max_agent_runs:
                reasons.append(BudgetDenialReason.AGENT_RUN_LIMIT_REACHED)
            if cost.target_agent is not None and (
                projected.agent_counts.get(cost.target_agent, 0)
                > budget.max_runs_per_agent
            ):
                reasons.append(BudgetDenialReason.AGENT_TYPE_LIMIT_REACHED)
            if projected.local_analyses_used > budget.max_local_analyses:
                reasons.append(BudgetDenialReason.LOCAL_ANALYSIS_LIMIT_REACHED)
            if (
                projected.execution_feedbacks_used
                > budget.max_execution_feedbacks
            ):
                reasons.append(BudgetDenialReason.EXECUTION_FEEDBACK_LIMIT_REACHED)
        if cost_reason is not None:
            reasons.append(cost_reason)

        if reasons:
            return BudgetEvaluation(
                BudgetDecision.DENY,
                False,
                reasons[0],
                tuple(reasons),
                "Actionは反復解析予算により拒否されました。",
                None,
            )
        return BudgetEvaluation(
            BudgetDecision.ALLOW,
            True,
            None,
            (),
            "Actionは反復解析予算内です。",
            projected,
        )

    def consume(
        self,
        *,
        usage: IterationUsage,
        action: IterationAction,
        cost: IterationActionCost,
        elapsed_seconds: float,
    ) -> IterationUsage:
        self._validate_elapsed(usage, elapsed_seconds)
        expected = self.cost_resolver.resolve(action)
        if cost != expected:
            raise ValueError("costがActionの標準Costと一致しません。")
        action_counts = dict(usage.action_counts)
        action_counts[action.action_type] = (
            action_counts.get(action.action_type, 0) + cost.actions
        )
        agent_counts = dict(usage.agent_counts)
        if cost.target_agent is not None:
            agent_counts[cost.target_agent] = (
                agent_counts.get(cost.target_agent, 0) + cost.agent_runs
            )
        return replace(
            usage,
            iterations_used=usage.iterations_used + cost.iterations,
            total_actions_used=usage.total_actions_used + cost.actions,
            agent_runs_used=usage.agent_runs_used + cost.agent_runs,
            ai_calls_used=usage.ai_calls_used + cost.ai_calls,
            local_analyses_used=usage.local_analyses_used + cost.local_analyses,
            execution_feedbacks_used=(
                usage.execution_feedbacks_used + cost.execution_feedbacks
            ),
            elapsed_seconds=elapsed_seconds,
            action_counts=action_counts,
            agent_counts=agent_counts,
        )

    def _validate_elapsed(
        self,
        usage: IterationUsage,
        elapsed_seconds: float,
    ) -> None:
        if (
            not isinstance(elapsed_seconds, (int, float))
            or isinstance(elapsed_seconds, bool)
            or not isfinite(elapsed_seconds)
            or elapsed_seconds < 0
        ):
            raise ValueError("elapsed_secondsは0以上の有限数で指定してください。")
        if elapsed_seconds < usage.elapsed_seconds:
            raise ValueError("elapsed_secondsを過去へ戻すことはできません。")
