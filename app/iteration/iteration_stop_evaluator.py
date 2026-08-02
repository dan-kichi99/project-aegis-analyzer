from app.iteration.iteration_action import IterationActionStatus
from app.iteration.iteration_state import (
    IterationSessionStatus,
    IterationStepStatus,
    IterationStopReason,
)
from app.iteration.iteration_stop_result import (
    IterationDecision,
    IterationStopContext,
    IterationStopEvaluation,
)

_MESSAGES = {
    IterationStopReason.ERROR: "致命的なエラーがあるため、反復解析を終了します。",
    IterationStopReason.USER_STOPPED: "ユーザーの要求により、反復解析を停止します。",
    IterationStopReason.AI_BUDGET_EXCEEDED: "AI呼び出し予算に到達したため、反復解析を停止します。",
    IterationStopReason.TIME_BUDGET_EXCEEDED: "時間予算に到達したため、反復解析を停止します。",
    IterationStopReason.MAX_ITERATIONS_REACHED: "最大反復回数に到達したため、反復解析を停止します。",
    IterationStopReason.REPEATED_STATE: "同じ解析状態が繰り返されたため、ユーザー確認へ進みます。",
    IterationStopReason.FLAG_CANDIDATE_FOUND: (
        "Flag候補が見つかりました。正解を保証しないため、ユーザー確認へ進みます。"
    ),
    IterationStopReason.NO_ACTIONS_AVAILABLE: (
        "実行可能なActionがないため、ユーザー確認へ進みます。"
    ),
}


class IterationStopEvaluator:
    """Sessionを変更せず、反復解析の停止条件だけを評価する。"""

    def evaluate(self, context: IterationStopContext) -> IterationStopEvaluation:
        if context.session.status is not IterationSessionStatus.ACTIVE:
            return self._existing_state(context)

        matched = self._matched_conditions(context)
        if not matched:
            return IterationStopEvaluation(
                decision=IterationDecision.CONTINUE,
                should_stop=False,
                reason=None,
                message="反復解析を継続できます。",
                matched_conditions=(),
                requires_user_confirmation=False,
            )
        reason = matched[0]
        return IterationStopEvaluation(
            decision=self._decision(reason),
            should_stop=True,
            reason=reason,
            message=_MESSAGES[reason],
            matched_conditions=matched,
            requires_user_confirmation=reason
            in {
                IterationStopReason.REPEATED_STATE,
                IterationStopReason.FLAG_CANDIDATE_FOUND,
                IterationStopReason.NO_ACTIONS_AVAILABLE,
            },
        )

    def _matched_conditions(
        self,
        context: IterationStopContext,
    ) -> tuple[IterationStopReason, ...]:
        session = context.session
        latest_failed = bool(
            session.steps
            and session.steps[-1].status is IterationStepStatus.FAILED
            and not self._has_continuing_action(context)
        )
        has_error = bool(context.fatal_error and context.fatal_error.strip()) or latest_failed
        ai_exceeded = (
            context.ai_calls_used is not None
            and context.ai_call_budget is not None
            and context.ai_calls_used >= context.ai_call_budget
        )
        time_exceeded = (
            context.elapsed_seconds is not None
            and context.time_budget_seconds is not None
            and context.elapsed_seconds >= context.time_budget_seconds
        )
        max_reached = session.current_iteration >= context.max_iterations
        has_flag = bool(session.flag_candidates) or session.primary_flag is not None
        checks = (
            (
                IterationStopReason.ERROR,
                has_error,
            ),
            (IterationStopReason.USER_STOPPED, context.user_requested_stop),
            (
                IterationStopReason.AI_BUDGET_EXCEEDED,
                ai_exceeded,
            ),
            (
                IterationStopReason.TIME_BUDGET_EXCEEDED,
                time_exceeded,
            ),
            (
                IterationStopReason.MAX_ITERATIONS_REACHED,
                max_reached,
            ),
            (IterationStopReason.REPEATED_STATE, context.repeated_state is True),
            (
                IterationStopReason.FLAG_CANDIDATE_FOUND,
                has_flag,
            ),
            (
                IterationStopReason.NO_ACTIONS_AVAILABLE,
                session.current_iteration > 0
                and not session.pending_actions
                and not has_error
                and not ai_exceeded
                and not time_exceeded
                and not max_reached
                and not has_flag,
            ),
        )
        return tuple(reason for reason, matches in checks if matches)

    def _has_continuing_action(self, context: IterationStopContext) -> bool:
        return any(
            action.status
            in {IterationActionStatus.PROPOSED, IterationActionStatus.APPROVED}
            for action in context.session.pending_actions
        )

    def _decision(self, reason: IterationStopReason) -> IterationDecision:
        if reason is IterationStopReason.ERROR:
            return IterationDecision.FAIL
        if reason is IterationStopReason.FLAG_CANDIDATE_FOUND:
            return IterationDecision.COMPLETE
        return IterationDecision.STOP

    def _existing_state(
        self,
        context: IterationStopContext,
    ) -> IterationStopEvaluation:
        session = context.session
        decisions = {
            IterationSessionStatus.COMPLETED: IterationDecision.COMPLETE,
            IterationSessionStatus.STOPPED: IterationDecision.STOP,
            IterationSessionStatus.FAILED: IterationDecision.FAIL,
        }
        reason = session.stop_reason
        if session.status is IterationSessionStatus.FAILED and reason is None:
            reason = IterationStopReason.ERROR
        message = (
            _MESSAGES.get(reason, "反復解析は既に終了しています。")
            if reason is not None
            else "反復解析は既に終了しています。"
        )
        return IterationStopEvaluation(
            decision=decisions[session.status],
            should_stop=True,
            reason=reason,
            message=message,
            matched_conditions=(reason,) if reason is not None else (),
            requires_user_confirmation=False,
        )
