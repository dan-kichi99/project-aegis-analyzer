from app.iteration.agent_iteration_coordinator import AgentIterationCoordinator
from app.iteration.agent_iteration_result import AgentIterationStatus
from app.iteration.execution_feedback_coordinator import ExecutionFeedbackCoordinator
from app.iteration.execution_feedback_result import ExecutionFeedbackStatus
from app.iteration.external_tool_iteration_coordinator import (
    ExternalToolIterationCoordinator,
)
from app.iteration.external_tool_iteration_result import ExternalToolIterationStatus
from app.iteration.iteration_action import (
    IterationAction,
    IterationActionStatus,
    IterationActionType,
)
from app.iteration.iteration_action_planner import IterationActionPlanner
from app.iteration.iteration_budget import BudgetDecision
from app.iteration.iteration_budget_manager import IterationBudgetManager
from app.iteration.iteration_coordinator import IterationCoordinator
from app.iteration.iteration_orchestration_result import (
    IterationOrchestrationResult,
    IterationOrchestrationStatus,
    IterationRunContext,
)
from app.iteration.iteration_state import (
    IterationSession,
    IterationSessionStatus,
    IterationStopReason,
)
from app.iteration.iteration_state_manager import IterationStateManager
from app.iteration.iteration_stop_evaluator import IterationStopEvaluator
from app.iteration.iteration_stop_result import (
    IterationDecision,
    IterationStopContext,
    IterationStopEvaluation,
)
from app.iteration.iteration_usage import IterationUsage
from app.iteration.local_analysis_result import LocalAnalysisStatus


class IterationOrchestrator:
    """1回の呼び出しで承認済みActionを最大1件だけ進める。"""

    def __init__(
        self,
        *,
        state_manager: IterationStateManager,
        action_planner: IterationActionPlanner,
        stop_evaluator: IterationStopEvaluator,
        budget_manager: IterationBudgetManager,
        local_coordinator: IterationCoordinator,
        agent_coordinator: AgentIterationCoordinator,
        feedback_coordinator: ExecutionFeedbackCoordinator,
        external_tool_coordinator: ExternalToolIterationCoordinator | None = None,
    ) -> None:
        self.state_manager = state_manager
        self.action_planner = action_planner
        self.stop_evaluator = stop_evaluator
        self.budget_manager = budget_manager
        self.local_coordinator = local_coordinator
        self.agent_coordinator = agent_coordinator
        self.feedback_coordinator = feedback_coordinator
        self.external_tool_coordinator = external_tool_coordinator

    def run_once(self, context: IterationRunContext) -> IterationOrchestrationResult:
        initial_stop = self._evaluate_stop(context, context.session, context.usage)
        if (
            initial_stop.should_stop
            and initial_stop.reason is not IterationStopReason.NO_ACTIONS_AVAILABLE
        ):
            session = self._apply_stop(context, context.session, initial_stop)
            status = self._stop_status(initial_stop)
            if initial_stop.requires_user_confirmation:
                status = IterationOrchestrationStatus.WAITING_APPROVAL
            return self._result(status, session, context, (), None, None, initial_stop)

        completed_ids = {
            action_id
            for step in context.session.steps
            for action_id in step.completed_action_ids
        }
        planned = self.action_planner.plan(
            agent_result=context.agent_result,
            judge_result=context.judge_result,
            execution_result=context.execution_result,
            hypotheses=context.session.hypotheses,
            open_questions=context.session.open_questions,
            existing_actions=context.session.pending_actions,
        )
        planned = tuple(
            action for action in planned if action.action_id not in completed_ids
        )
        session = self.state_manager.add_pending_actions(
            context.session, planned, context.updated_at
        )
        approved = tuple(
            sorted(
                (
                    action
                    for action in session.pending_actions
                    if action.status is IterationActionStatus.APPROVED
                ),
                key=lambda action: (-action.priority, action.action_id),
            )
        )
        if not approved:
            stop = self._evaluate_stop(context, session, context.usage)
            if stop.should_stop:
                stopped_session = self._apply_stop(context, session, stop)
                status = (
                    IterationOrchestrationStatus.WAITING_APPROVAL
                    if stop.requires_user_confirmation
                    else self._stop_status(stop)
                )
                return self._result(
                    status,
                    stopped_session,
                    context,
                    planned,
                    None,
                    None,
                    stop,
                )
            status = (
                IterationOrchestrationStatus.WAITING_APPROVAL
                if session.pending_actions
                else IterationOrchestrationStatus.NO_ACTION
            )
            message = (
                "実行候補を作成しました。承認されたActionはありません。"
                if session.pending_actions
                else "実行可能なActionはありません。"
            )
            return self._result(status, session, context, planned, None, None, stop, message)

        action = approved[0]
        self._validate_action_input(context, action)
        budget_evaluation = self.budget_manager.evaluate_action(
            session=session,
            action=action,
            budget=context.budget,
            usage=context.usage,
            elapsed_seconds=context.elapsed_seconds,
        )
        if budget_evaluation.decision is BudgetDecision.DENY:
            stop = self._evaluate_stop(context, session, context.usage)
            session = self._apply_stop(context, session, stop)
            return self._result(
                IterationOrchestrationStatus.BUDGET_DENIED,
                session,
                context,
                planned,
                action,
                budget_evaluation,
                stop,
                "予算上限によりActionを実行できませんでした。",
            )

        cost = self.budget_manager.cost_resolver.resolve(action)
        local_execution = None
        agent_execution = None
        feedback_execution = None
        external_tool_execution = None
        if action.action_type is IterationActionType.RUN_LOCAL_ANALYSIS:
            local_execution = self.local_coordinator.execute_action(
                session=session,
                action_id=action.action_id,
                updated_at=context.updated_at,
            )
            new_session = local_execution.session
            action_status = self._local_status(local_execution.local_result.status)
        elif action.action_type is IterationActionType.RUN_AGENT:
            agent_execution = self.agent_coordinator.execute_action(
                session=session,
                action_id=action.action_id,
                agent_input=context.agent_input,
                updated_at=context.updated_at,
            )
            new_session = agent_execution.session
            action_status = self._agent_status(
                agent_execution.agent_iteration_result.status
            )
        elif action.action_type is IterationActionType.RUN_EXTERNAL_TOOL:
            if self.external_tool_coordinator is None:
                raise ValueError("RUN_EXTERNAL_TOOLにはCoordinatorが必要です。")
            external_tool_execution = self.external_tool_coordinator.execute_action(
                session=session,
                action_id=action.action_id,
                challenge=context.challenge,
                working_directory=context.working_directory,
                updated_at=context.updated_at,
            )
            new_session = external_tool_execution.session
            action_status = self._external_tool_status(
                external_tool_execution.tool_iteration_result.status
            )
        else:
            feedback_execution = self.feedback_coordinator.apply_feedback(
                session=session,
                action_id=action.action_id,
                execution_analysis=context.execution_result,
                source_index=context.execution_source_index,
                updated_at=context.updated_at,
            )
            new_session = feedback_execution.session
            action_status = self._feedback_status(
                feedback_execution.feedback_result.status
            )

        usage = self.budget_manager.consume(
            usage=context.usage,
            action=action,
            cost=cost,
            elapsed_seconds=context.elapsed_seconds,
        )
        stop = self._evaluate_stop(context, new_session, usage)
        final_session = self._apply_stop(context, new_session, stop)
        status = action_status
        if stop.should_stop:
            status = (
                IterationOrchestrationStatus.WAITING_APPROVAL
                if stop.requires_user_confirmation
                else self._stop_status(stop)
            )
        return IterationOrchestrationResult(
            status=status,
            session=final_session,
            usage=usage,
            planned_actions=planned,
            selected_action=action,
            budget_evaluation=budget_evaluation,
            stop_evaluation=stop,
            message="承認済みActionを1件実行しました。",
            local_execution=local_execution,
            agent_execution=agent_execution,
            feedback_execution=feedback_execution,
            external_tool_execution=external_tool_execution,
        )

    def _validate_action_input(
        self, context: IterationRunContext, action: IterationAction
    ) -> None:
        if action.action_type is IterationActionType.RUN_AGENT:
            if context.agent_input is None:
                raise ValueError("RUN_AGENTにはagent_inputが必要です。")
            if action.target_agent is None:
                raise ValueError("RUN_AGENTにはtarget_agentが必要です。")
        elif action.action_type is IterationActionType.ANALYZE_EXECUTION_OUTPUT:
            if context.execution_result is None:
                raise ValueError("ANALYZE_EXECUTION_OUTPUTにはexecution_resultが必要です。")
            if context.execution_source_index is None:
                raise ValueError("ANALYZE_EXECUTION_OUTPUTにはsource_indexが必要です。")

        if action.action_type is IterationActionType.RUN_EXTERNAL_TOOL:
            if context.challenge is None:
                raise ValueError("RUN_EXTERNAL_TOOLにはchallengeが必要です。")
            if context.working_directory is None:
                raise ValueError("RUN_EXTERNAL_TOOLにはworking_directoryが必要です。")

    def _evaluate_stop(
        self,
        context: IterationRunContext,
        session: IterationSession,
        usage: IterationUsage,
    ) -> IterationStopEvaluation:
        return self.stop_evaluator.evaluate(
            IterationStopContext(
                session=session,
                max_iterations=context.budget.max_iterations,
                elapsed_seconds=context.elapsed_seconds,
                time_budget_seconds=context.budget.max_elapsed_seconds,
                ai_calls_used=usage.ai_calls_used,
                ai_call_budget=context.budget.max_ai_calls,
                user_requested_stop=context.user_requested_stop,
                fatal_error=context.fatal_error,
                repeated_state=context.repeated_state,
            )
        )

    def _apply_stop(
        self,
        context: IterationRunContext,
        session: IterationSession,
        evaluation: IterationStopEvaluation,
    ) -> IterationSession:
        if (
            not evaluation.should_stop
            or evaluation.requires_user_confirmation
            or evaluation.reason is None
            or session.status is not IterationSessionStatus.ACTIVE
        ):
            return session
        return self.state_manager.stop_session(
            session, evaluation.reason, context.updated_at
        )

    def _stop_status(
        self, evaluation: IterationStopEvaluation
    ) -> IterationOrchestrationStatus:
        return {
            IterationDecision.COMPLETE: IterationOrchestrationStatus.COMPLETED,
            IterationDecision.STOP: IterationOrchestrationStatus.STOPPED,
            IterationDecision.FAIL: IterationOrchestrationStatus.FAILED,
            IterationDecision.CONTINUE: IterationOrchestrationStatus.CONTINUE,
        }[evaluation.decision]

    def _local_status(self, status: LocalAnalysisStatus) -> IterationOrchestrationStatus:
        return {
            LocalAnalysisStatus.COMPLETED: IterationOrchestrationStatus.ACTION_COMPLETED,
            LocalAnalysisStatus.SKIPPED: IterationOrchestrationStatus.ACTION_SKIPPED,
            LocalAnalysisStatus.FAILED: IterationOrchestrationStatus.ACTION_FAILED,
        }[status]

    def _agent_status(self, status: AgentIterationStatus) -> IterationOrchestrationStatus:
        return {
            AgentIterationStatus.COMPLETED: IterationOrchestrationStatus.ACTION_COMPLETED,
            AgentIterationStatus.SKIPPED: IterationOrchestrationStatus.ACTION_SKIPPED,
            AgentIterationStatus.REPEATED: IterationOrchestrationStatus.ACTION_SKIPPED,
            AgentIterationStatus.FAILED: IterationOrchestrationStatus.ACTION_FAILED,
        }[status]

    def _feedback_status(
        self, status: ExecutionFeedbackStatus
    ) -> IterationOrchestrationStatus:
        return {
            ExecutionFeedbackStatus.COMPLETED: IterationOrchestrationStatus.ACTION_COMPLETED,
            ExecutionFeedbackStatus.SKIPPED: IterationOrchestrationStatus.ACTION_SKIPPED,
            ExecutionFeedbackStatus.REPEATED: IterationOrchestrationStatus.ACTION_SKIPPED,
            ExecutionFeedbackStatus.FAILED: IterationOrchestrationStatus.ACTION_FAILED,
        }[status]

    def _external_tool_status(
        self, status: ExternalToolIterationStatus
    ) -> IterationOrchestrationStatus:
        return {
            ExternalToolIterationStatus.COMPLETED: (
                IterationOrchestrationStatus.ACTION_COMPLETED
            ),
            ExternalToolIterationStatus.SKIPPED: (
                IterationOrchestrationStatus.ACTION_SKIPPED
            ),
            ExternalToolIterationStatus.REPEATED: (
                IterationOrchestrationStatus.ACTION_SKIPPED
            ),
            ExternalToolIterationStatus.FAILED: (
                IterationOrchestrationStatus.ACTION_FAILED
            ),
        }[status]

    def _result(
        self,
        status: IterationOrchestrationStatus,
        session: IterationSession,
        context: IterationRunContext,
        planned: tuple[IterationAction, ...],
        selected: IterationAction | None,
        budget_evaluation,
        stop_evaluation: IterationStopEvaluation,
        message: str = "反復解析の停止条件を確認しました。",
    ) -> IterationOrchestrationResult:
        return IterationOrchestrationResult(
            status,
            session,
            context.usage,
            planned,
            selected,
            budget_evaluation,
            stop_evaluation,
            message,
        )
