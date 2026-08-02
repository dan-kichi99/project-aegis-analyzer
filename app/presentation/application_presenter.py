from dataclasses import replace

from app.agents.agent_aggregate_result import AgentAggregateResult
from app.events.analysis_event import AnalysisEvent, AnalysisEventType
from app.iteration.iteration_budget import IterationBudget
from app.iteration.iteration_state import IterationSession
from app.iteration.iteration_usage import IterationUsage
from app.judge.judge_result import JudgeResult
from app.presentation.view_models import (
    ActionViewModel,
    AgentViewModel,
    ApplicationState,
    ApplicationStatus,
    BudgetViewModel,
    ExternalToolViewModel,
    IterationViewModel,
    ProgressViewModel,
    ResultViewModel,
)


class ApplicationPresenter:
    def initial_state(self) -> ApplicationState:
        return ApplicationState(
            progress=ProgressViewModel(
                ApplicationStatus.IDLE, "idle", "待機中です。", None, None, None
            ),
            result=None,
            agent=None,
            iteration=None,
            budget=None,
            external_tools=(),
        )

    def apply_event(
        self, state: ApplicationState, event: AnalysisEvent
    ) -> ApplicationState:
        status, message = self._event_display(event.event_type)
        agent = None
        if event.event_type is AnalysisEventType.AGENT_STARTED:
            raw_agent = event.metadata.get("agent_type")
            if isinstance(raw_agent, str):
                agent = raw_agent[:100]
        elif event.event_type not in {
            AnalysisEventType.AGENT_COMPLETED,
            AnalysisEventType.AGENT_FAILED,
        }:
            agent = state.progress.current_agent
        error_type = None
        if event.event_type is AnalysisEventType.ANALYSIS_FAILED:
            raw_error = event.metadata.get("error_type")
            if isinstance(raw_error, str):
                error_type = raw_error[:100]
        progress = ProgressViewModel(
            status=status,
            phase=event.phase[:100],
            message=message,
            progress_percent=None,
            current_agent=agent,
            error_type=error_type,
        )
        return replace(state, progress=progress)

    def present_result(
        self, state: ApplicationState, result: JudgeResult
    ) -> ApplicationState:
        flag = result.flag
        view = ResultViewModel(
            solved=flag is not None,
            category=(result.category or "Unknown")[:100],
            answer=(result.answer or "")[:20_000],
            flag_candidate=flag,
            confidence=result.confidence,
            reason=(result.reason or "")[:2_000],
            next_actions=tuple(
                action[:500] for action in (result.next_actions or [])[:20]
            ),
            warning=(
                "Flagは候補です。正解確定や提出は行われていません。"
                if flag is not None
                else None
            ),
        )
        agent = self._agent_view(result.agent_result)
        return replace(state, result=view, agent=agent)

    def present_iteration(
        self,
        state: ApplicationState,
        session: IterationSession,
        usage: IterationUsage | None = None,
        budget: IterationBudget | None = None,
    ) -> ApplicationState:
        actions = tuple(
            ActionViewModel(
                action.action_id,
                action.action_type.value,
                action.status.value,
                action.priority,
                action.description[:1_000],
                action.requires_user_approval,
            )
            for action in session.pending_actions
        )
        iteration = IterationViewModel(
            session.session_id,
            session.status.value,
            session.current_iteration,
            actions,
            tuple(item.statement[:1_000] for item in session.hypotheses),
            tuple(item.question[:1_000] for item in session.open_questions),
            session.flag_candidates[:20],
            session.stop_reason.value if session.stop_reason is not None else None,
        )
        budget_view = self._budget_view(usage, budget)
        tools = tuple(
            self._tool_view(step.external_tool_result)
            for step in session.steps
            if step.external_tool_result is not None
        )
        return replace(
            state,
            iteration=iteration,
            budget=budget_view,
            external_tools=tools,
        )

    def _event_display(
        self, event_type: AnalysisEventType
    ) -> tuple[ApplicationStatus, str]:
        values = {
            AnalysisEventType.ANALYSIS_STARTED: (
                ApplicationStatus.ANALYZING,
                "解析を開始しました。",
            ),
            AnalysisEventType.AGENT_PLAN_CREATED: (
                ApplicationStatus.ANALYZING,
                "専門Agentの実行計画を作成しました。",
            ),
            AnalysisEventType.AGENT_STARTED: (
                ApplicationStatus.ANALYZING,
                "専門Agentの解析を開始しました。",
            ),
            AnalysisEventType.AGENT_COMPLETED: (
                ApplicationStatus.ANALYZING,
                "専門Agentの解析が完了しました。",
            ),
            AnalysisEventType.AGENT_FAILED: (
                ApplicationStatus.ANALYZING,
                "専門Agentの解析に失敗しました。",
            ),
            AnalysisEventType.LOCAL_SOLUTION_FOUND: (
                ApplicationStatus.WAITING_APPROVAL,
                "ローカル解析でFlag候補を検出しました。",
            ),
            AnalysisEventType.ANALYSIS_COMPLETED: (
                ApplicationStatus.COMPLETED,
                "解析が完了しました。",
            ),
            AnalysisEventType.ANALYSIS_FAILED: (
                ApplicationStatus.FAILED,
                "解析中にエラーが発生しました。",
            ),
            AnalysisEventType.ANALYSIS_CANCELLED: (
                ApplicationStatus.IDLE,
                "解析をキャンセルしました。",
            ),
        }
        return values.get(
            event_type,
            (ApplicationStatus.ANALYZING, "解析処理を更新しました。"),
        )

    def _agent_view(
        self, aggregate: AgentAggregateResult | None
    ) -> AgentViewModel | None:
        if aggregate is None:
            return None
        primary = aggregate.primary_result
        return AgentViewModel(
            primary_agent=primary.agent_type.value if primary is not None else None,
            executed_agents=tuple(item.agent_type.value for item in aggregate.results),
            status=aggregate.status.value,
            confidence=aggregate.confidence,
            evidence=tuple(
                f"{item.source}: {item.detail}"[:1_000]
                for item in aggregate.evidence[:30]
            ),
            flag_candidates=aggregate.flag_candidates[:20],
            conflicts=tuple(
                (
                    f"{item.field}: {', '.join(item.values)} "
                    f"({', '.join(agent.value for agent in item.agents)})"
                )[:1_000]
                for item in aggregate.conflicts[:20]
            ),
            used_fallback=aggregate.used_fallback,
        )

    def _budget_view(
        self, usage: IterationUsage | None, budget: IterationBudget | None
    ) -> BudgetViewModel | None:
        if usage is None or budget is None:
            return None
        return BudgetViewModel(
            usage.iterations_used,
            budget.max_iterations,
            usage.total_actions_used,
            budget.max_total_actions,
            usage.agent_runs_used,
            budget.max_agent_runs,
            usage.ai_calls_used,
            budget.max_ai_calls,
            usage.local_analyses_used,
            budget.max_local_analyses,
            usage.execution_feedbacks_used,
            budget.max_execution_feedbacks,
            usage.external_tool_runs_used,
            budget.max_external_tool_runs,
            usage.elapsed_seconds,
            budget.max_elapsed_seconds,
        )

    def _tool_view(self, result) -> ExternalToolViewModel:
        return ExternalToolViewModel(
            result.tool_type.value,
            result.status.value,
            result.target_path.name,
            result.summary[:500],
            result.tool_result.exit_code,
            tuple(
                f"{item.source}: {item.detail}"[:1_000]
                for item in result.tool_result.evidence[:30]
            ),
            result.repeated,
            result.error_message[:500] if result.error_message is not None else None,
        )
