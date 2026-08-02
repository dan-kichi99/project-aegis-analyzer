from dataclasses import dataclass
from datetime import datetime

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
from app.iteration.local_analysis_executor import (
    BaseLocalAnalysisExecutor,
    LocalAnalysisRequest,
)
from app.iteration.local_analysis_result import (
    LocalAnalysisResult,
    LocalAnalysisStatus,
)

MAX_EXECUTOR_ERROR_CHARACTERS = 500


@dataclass(slots=True, frozen=True)
class IterationExecutionResult:
    session: IterationSession
    action: IterationAction
    local_result: LocalAnalysisResult
    step: IterationStep


class IterationCoordinator:
    """承認済みローカル解析Actionを1回処理し、Stepへ記録する。"""

    def __init__(
        self,
        *,
        state_manager: IterationStateManager,
        executors: tuple[BaseLocalAnalysisExecutor, ...],
    ) -> None:
        registered: dict[str, BaseLocalAnalysisExecutor] = {}
        for executor in executors:
            if not isinstance(executor.analysis_type, str) or not executor.analysis_type.strip():
                raise ValueError("Executorのanalysis_typeは非空文字列で指定してください。")
            if executor.analysis_type in registered:
                raise ValueError(
                    f"analysis_type「{executor.analysis_type}」が重複しています。"
                )
            registered[executor.analysis_type] = executor
        self.state_manager = state_manager
        self.executors = tuple(executors)
        self._registered = registered

    def execute_action(
        self,
        *,
        session: IterationSession,
        action_id: str,
        updated_at: datetime,
    ) -> IterationExecutionResult:
        action, analysis_type, executor = self._validate(
            session,
            action_id,
            updated_at,
        )
        request = LocalAnalysisRequest(session, action)
        try:
            local_result = executor.execute(request)
        except Exception as error:  # noqa: BLE001 - 失敗を履歴DTOへ変換
            detail = f"{type(error).__name__}: {error}"[:MAX_EXECUTOR_ERROR_CHARACTERS]
            local_result = LocalAnalysisResult(
                action_id=action.action_id,
                analysis_type=analysis_type,
                status=LocalAnalysisStatus.FAILED,
                summary="ローカル解析Executorの実行中にエラーが発生しました。",
                hypotheses=(),
                open_questions=(),
                flag_candidates=(),
                next_actions=(),
                error_message=detail,
            )
        step = self._step(session, action, local_result)
        appended = self.state_manager.append_step(session, step, updated_at)
        final_status = {
            LocalAnalysisStatus.COMPLETED: IterationActionStatus.COMPLETED,
            LocalAnalysisStatus.SKIPPED: IterationActionStatus.SKIPPED,
            LocalAnalysisStatus.FAILED: IterationActionStatus.FAILED,
        }[local_result.status]
        finalized = self.state_manager.complete_action(
            appended,
            action.action_id,
            final_status,
            updated_at,
        )
        return IterationExecutionResult(finalized, action, local_result, step)

    def _validate(
        self,
        session: IterationSession,
        action_id: str,
        updated_at: datetime,
    ) -> tuple[IterationAction, str, BaseLocalAnalysisExecutor]:
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
        if action.action_type is not IterationActionType.RUN_LOCAL_ANALYSIS:
            raise ValueError("RUN_LOCAL_ANALYSIS Actionだけを実行できます。")
        analysis_type = action.metadata.get("analysis_type")
        if not isinstance(analysis_type, str) or not analysis_type.strip():
            raise ValueError("metadataに非空のanalysis_typeが必要です。")
        executor = self._registered.get(analysis_type)
        if executor is None:
            raise ValueError(f"analysis_type「{analysis_type}」は登録されていません。")
        return action, analysis_type, executor

    def _step(
        self,
        session: IterationSession,
        action: IterationAction,
        result: LocalAnalysisResult,
    ) -> IterationStep:
        status = {
            LocalAnalysisStatus.COMPLETED: IterationStepStatus.COMPLETED,
            LocalAnalysisStatus.SKIPPED: IterationStepStatus.SKIPPED,
            LocalAnalysisStatus.FAILED: IterationStepStatus.FAILED,
        }[result.status]
        completed_ids = (
            (action.action_id,)
            if result.status in {LocalAnalysisStatus.COMPLETED, LocalAnalysisStatus.SKIPPED}
            else ()
        )
        return IterationStep(
            iteration_number=session.current_iteration + 1,
            status=status,
            summary=result.summary,
            agent_result=None,
            execution_result=None,
            hypotheses=result.hypotheses,
            open_questions=result.open_questions,
            proposed_actions=result.next_actions,
            completed_action_ids=completed_ids,
            error_message=(
                result.error_message
                if result.status is LocalAnalysisStatus.FAILED
                else None
            ),
        )
