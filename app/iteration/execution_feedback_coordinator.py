from dataclasses import dataclass
from datetime import datetime

from app.execution.execution_analysis_result import ExecutionAnalysisResult
from app.execution.execution_result import ExecutionStatus
from app.iteration.execution_feedback_result import (
    MAX_FEEDBACK_ITEMS,
    ExecutionFeedbackResult,
    ExecutionFeedbackStatus,
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
    OpenQuestion,
    OpenQuestionStatus,
)
from app.iteration.iteration_state_manager import IterationStateManager


@dataclass(slots=True, frozen=True)
class ExecutionFeedbackRequest:
    session: IterationSession
    action: IterationAction
    execution_analysis: ExecutionAnalysisResult
    source_index: int

    def __post_init__(self) -> None:
        if self.source_index < 0:
            raise ValueError("source_indexは0以上で指定してください。")


@dataclass(slots=True, frozen=True)
class ExecutionFeedbackExecutionResult:
    session: IterationSession
    action: IterationAction
    feedback_result: ExecutionFeedbackResult
    step: IterationStep


class ExecutionFeedbackCoordinator:
    """解析済みPython実行結果を反復Stepへ取り込む。"""

    def __init__(self, *, state_manager: IterationStateManager) -> None:
        self.state_manager = state_manager

    def apply_feedback(
        self,
        *,
        session: IterationSession,
        action_id: str,
        execution_analysis: ExecutionAnalysisResult,
        source_index: int,
        updated_at: datetime,
    ) -> ExecutionFeedbackExecutionResult:
        action = self._validate(session, action_id, source_index, updated_at)
        repeated = any(
            step.feedback_source_index == source_index for step in session.steps
        )
        if repeated:
            status = ExecutionFeedbackStatus.REPEATED
            summary = "同じ実行結果は既に反復Sessionへ取り込み済みです。"
            questions: tuple[OpenQuestion, ...] = ()
            error_message = None
        elif not execution_analysis.execution.started:
            status = ExecutionFeedbackStatus.FAILED
            summary = "実行されていない結果は解析フィードバックとして取り込めません。"
            questions = ()
            error_message = "Python実行が開始されていません。"
        else:
            status = ExecutionFeedbackStatus.COMPLETED
            summary = self._summary(execution_analysis)
            questions = self._questions(execution_analysis, source_index)
            error_message = None

        flags = tuple(
            dict.fromkeys(item.flag for item in execution_analysis.flag_candidates)
        )[:MAX_FEEDBACK_ITEMS]
        feedback = ExecutionFeedbackResult(
            action_id=action.action_id,
            source_index=source_index,
            status=status,
            summary=summary,
            execution_analysis=execution_analysis,
            flag_candidates=flags,
            open_questions=questions,
            next_actions=(),
            repeated=repeated,
            error_message=error_message,
        )
        step = self._step(session, action, feedback)
        appended = self.state_manager.append_step(session, step, updated_at)
        final_status = {
            ExecutionFeedbackStatus.COMPLETED: IterationActionStatus.COMPLETED,
            ExecutionFeedbackStatus.SKIPPED: IterationActionStatus.SKIPPED,
            ExecutionFeedbackStatus.REPEATED: IterationActionStatus.SKIPPED,
            ExecutionFeedbackStatus.FAILED: IterationActionStatus.FAILED,
        }[status]
        finalized = self.state_manager.complete_action(
            appended, action.action_id, final_status, updated_at
        )
        return ExecutionFeedbackExecutionResult(finalized, action, feedback, step)

    def _validate(
        self,
        session: IterationSession,
        action_id: str,
        source_index: int,
        updated_at: datetime,
    ) -> IterationAction:
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
            raise ValueError("APPROVED Actionだけを処理できます。")
        if action.action_type is not IterationActionType.ANALYZE_EXECUTION_OUTPUT:
            raise ValueError("ANALYZE_EXECUTION_OUTPUT Actionだけを処理できます。")
        metadata_index = action.metadata.get("source_index")
        if not isinstance(metadata_index, int) or isinstance(metadata_index, bool):
            raise ValueError(  # noqa: TRY004 - 公開APIの入力違反はValueErrorへ統一
                "metadata source_indexはintで指定してください。"
            )
        if metadata_index < 0 or source_index < 0:
            raise ValueError("source_indexは0以上で指定してください。")
        if metadata_index != source_index:
            raise ValueError("metadataと引数のsource_indexが一致しません。")
        return action

    def _summary(self, analysis: ExecutionAnalysisResult) -> str:
        execution = analysis.execution
        return (
            "実行結果を反復Sessionへ取り込みました。"
            f" status={execution.status.value}, exit_code={execution.exit_code},"
            f" timed_out={execution.timed_out},"
            f" output_truncated={execution.output_truncated},"
            f" successful_execution={analysis.successful_execution}"
        )

    def _questions(
        self,
        analysis: ExecutionAnalysisResult,
        source_index: int,
    ) -> tuple[OpenQuestion, ...]:
        execution = analysis.execution
        values: list[OpenQuestion] = []
        if execution.status is ExecutionStatus.FAILED or (
            execution.exit_code is not None and execution.exit_code != 0
        ):
            values.append(
                self._question(
                    source_index,
                    "failure",
                    "実行が正常終了しなかった原因を確認してください。",
                )
            )
        if execution.timed_out or execution.status is ExecutionStatus.TIMED_OUT:
            values.append(
                self._question(
                    source_index,
                    "timeout",
                    "実行がタイムアウトした原因を確認してください。",
                )
            )
        if execution.output_truncated:
            values.append(
                self._question(
                    source_index,
                    "truncated",
                    "省略された出力に追加の手掛かりがないか確認してください。",
                )
            )
        return tuple(values)

    def _question(self, source_index: int, suffix: str, text: str) -> OpenQuestion:
        return OpenQuestion(
            question_id=f"execution:{source_index}:{suffix}",
            question=text,
            source="execution_feedback",
            status=OpenQuestionStatus.OPEN,
            resolution=None,
        )

    def _step(
        self,
        session: IterationSession,
        action: IterationAction,
        result: ExecutionFeedbackResult,
    ) -> IterationStep:
        status = {
            ExecutionFeedbackStatus.COMPLETED: IterationStepStatus.COMPLETED,
            ExecutionFeedbackStatus.SKIPPED: IterationStepStatus.SKIPPED,
            ExecutionFeedbackStatus.REPEATED: IterationStepStatus.SKIPPED,
            ExecutionFeedbackStatus.FAILED: IterationStepStatus.FAILED,
        }[result.status]
        completed_ids = (
            ()
            if result.status is ExecutionFeedbackStatus.FAILED
            else (action.action_id,)
        )
        return IterationStep(
            iteration_number=session.current_iteration + 1,
            status=status,
            summary=result.summary,
            agent_result=None,
            execution_result=result.execution_analysis,
            hypotheses=(),
            open_questions=result.open_questions,
            proposed_actions=(),
            completed_action_ids=completed_ids,
            error_message=result.error_message,
            feedback_source_index=result.source_index,
        )
