from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.challenge.challenge_input import ChallengeInput
from app.external_tools.tool import BaseExternalTool, ExternalToolType
from app.external_tools.tool_request import ToolRequest
from app.external_tools.tool_result import ExternalToolStatus, ToolResult
from app.iteration.external_tool_iteration_result import (
    MAX_EXTERNAL_TOOL_ITERATION_TEXT_CHARACTERS,
    ExternalToolIterationExecutionResult,
    ExternalToolIterationResult,
    ExternalToolIterationStatus,
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
class _ValidatedAction:
    action: IterationAction
    tool_type: ExternalToolType
    target_path: Path
    tool: BaseExternalTool


class ExternalToolIterationCoordinator:
    def __init__(
        self,
        *,
        state_manager: IterationStateManager,
        tools: tuple[BaseExternalTool, ...],
        max_runs_per_tool: int = 2,
    ) -> None:
        if (
            not isinstance(max_runs_per_tool, int)
            or isinstance(max_runs_per_tool, bool)
            or max_runs_per_tool < 1
        ):
            raise ValueError("max_runs_per_toolは1以上の整数で指定してください。")
        registered: dict[ExternalToolType, BaseExternalTool] = {}
        for tool in tools:
            if tool.tool_type is ExternalToolType.CUSTOM:
                raise ValueError("CUSTOM Toolは登録できません。")
            if tool.tool_type in registered:
                raise ValueError("同じTool種別を重複登録できません。")
            registered[tool.tool_type] = tool
        self.state_manager = state_manager
        self.tools = tuple(tools)
        self.max_runs_per_tool = max_runs_per_tool
        self._registered = registered

    def execute_action(
        self,
        *,
        session: IterationSession,
        action_id: str,
        challenge: ChallengeInput,
        working_directory: Path,
        updated_at: datetime,
    ) -> ExternalToolIterationExecutionResult:
        validated = self._validate(session, action_id, updated_at)
        if self._run_count(session, validated.tool_type) >= self.max_runs_per_tool:
            raise ValueError("Tool種別ごとの実行回数上限に達しています。")
        request = ToolRequest(
            challenge=challenge,
            working_directory=working_directory,
            metadata={"target_path": validated.target_path},
        )
        try:
            tool_result = validated.tool.execute(request)
        except Exception as error:  # noqa: BLE001 - Tool例外を履歴DTOへ変換
            detail = f"{type(error).__name__}: {error}"[
                :MAX_EXTERNAL_TOOL_ITERATION_TEXT_CHARACTERS
            ]
            tool_result = ToolResult(
                tool_type=validated.tool_type,
                status=ExternalToolStatus.FAILED,
                summary="外部Toolの実行中にエラーが発生しました。",
                stdout="",
                stderr="",
                exit_code=None,
                evidence=(),
                error_message=detail,
            )
        status = self._status(tool_result.status)
        repeated = self._is_repeated(
            session,
            validated.tool_type,
            validated.target_path,
            tool_result,
        )
        if repeated:
            status = ExternalToolIterationStatus.REPEATED
        summary = (
            "過去と同一の外部Tool結果を検出しました。"
            if repeated
            else tool_result.summary
        )[:MAX_EXTERNAL_TOOL_ITERATION_TEXT_CHARACTERS]
        iteration_result = ExternalToolIterationResult(
            action_id=validated.action.action_id,
            tool_type=validated.tool_type,
            target_path=validated.target_path,
            status=status,
            tool_result=tool_result,
            summary=summary,
            repeated=repeated,
            error_message=(
                tool_result.error_message
                if status is ExternalToolIterationStatus.FAILED
                else None
            ),
        )
        step = self._step(session, validated.action, iteration_result)
        appended = self.state_manager.append_step(session, step, updated_at)
        action_status = {
            ExternalToolIterationStatus.COMPLETED: IterationActionStatus.COMPLETED,
            ExternalToolIterationStatus.SKIPPED: IterationActionStatus.SKIPPED,
            ExternalToolIterationStatus.REPEATED: IterationActionStatus.SKIPPED,
            ExternalToolIterationStatus.FAILED: IterationActionStatus.FAILED,
        }[status]
        finalized = self.state_manager.complete_action(
            appended,
            validated.action.action_id,
            action_status,
            updated_at,
        )
        return ExternalToolIterationExecutionResult(
            finalized, validated.action, iteration_result, step
        )

    def _validate(
        self,
        session: IterationSession,
        action_id: str,
        updated_at: datetime,
    ) -> _ValidatedAction:
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
            raise ValueError("対象Actionはpending_actionsに1件だけ必要です。")
        action = matches[0]
        if action.status is not IterationActionStatus.APPROVED:
            raise ValueError("APPROVED Actionだけを実行できます。")
        if action.action_type is not IterationActionType.RUN_EXTERNAL_TOOL:
            raise ValueError("RUN_EXTERNAL_TOOL Actionだけを実行できます。")
        raw_type = action.metadata.get("tool_type")
        try:
            tool_type = (
                raw_type
                if isinstance(raw_type, ExternalToolType)
                else ExternalToolType(raw_type)
            )
        except (TypeError, ValueError) as error:
            raise ValueError("metadataに有効なtool_typeが必要です。") from error
        if tool_type is ExternalToolType.CUSTOM:
            raise ValueError("CUSTOM Toolは実行できません。")
        target_path = action.metadata.get("target_path")
        if not isinstance(target_path, Path) or not target_path.is_absolute():
            raise ValueError("target_pathは絶対Pathで指定してください。")
        tool = self._registered.get(tool_type)
        if tool is None:
            raise ValueError("対象Tool Adapterは登録されていません。")
        return _ValidatedAction(action, tool_type, target_path, tool)

    def _run_count(
        self, session: IterationSession, tool_type: ExternalToolType
    ) -> int:
        return sum(
            step.external_tool_result.tool_type is tool_type
            for step in session.steps
            if step.external_tool_result is not None
        )

    def _is_repeated(
        self,
        session: IterationSession,
        tool_type: ExternalToolType,
        target_path: Path,
        tool_result: ToolResult,
    ) -> bool:
        fingerprint = self._fingerprint(tool_result)
        return any(
            previous.tool_type is tool_type
            and previous.target_path == target_path
            and self._fingerprint(previous.tool_result) == fingerprint
            for step in session.steps
            if (previous := step.external_tool_result) is not None
        )

    def _fingerprint(self, result: ToolResult) -> tuple[object, ...]:
        return (
            result.tool_type,
            result.status,
            result.summary,
            result.stdout,
            result.stderr,
            result.exit_code,
            result.evidence,
            result.error_message,
        )

    def _status(self, status: ExternalToolStatus) -> ExternalToolIterationStatus:
        return {
            ExternalToolStatus.COMPLETED: ExternalToolIterationStatus.COMPLETED,
            ExternalToolStatus.SKIPPED: ExternalToolIterationStatus.SKIPPED,
            ExternalToolStatus.NOT_RUN: ExternalToolIterationStatus.SKIPPED,
            ExternalToolStatus.FAILED: ExternalToolIterationStatus.FAILED,
        }[status]

    def _step(
        self,
        session: IterationSession,
        action: IterationAction,
        result: ExternalToolIterationResult,
    ) -> IterationStep:
        status = {
            ExternalToolIterationStatus.COMPLETED: IterationStepStatus.COMPLETED,
            ExternalToolIterationStatus.SKIPPED: IterationStepStatus.SKIPPED,
            ExternalToolIterationStatus.REPEATED: IterationStepStatus.SKIPPED,
            ExternalToolIterationStatus.FAILED: IterationStepStatus.FAILED,
        }[result.status]
        return IterationStep(
            iteration_number=session.current_iteration + 1,
            status=status,
            summary=result.summary,
            agent_result=None,
            execution_result=None,
            hypotheses=(),
            open_questions=(),
            proposed_actions=(),
            completed_action_ids=(
                (action.action_id,)
                if result.status is not ExternalToolIterationStatus.FAILED
                else ()
            ),
            error_message=(
                result.error_message
                if result.status is ExternalToolIterationStatus.FAILED
                else None
            ),
            external_tool_result=result,
        )
