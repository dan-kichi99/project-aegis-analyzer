from abc import abstractmethod
from pathlib import Path

from app.external_tools.process_result import (
    ExternalProcessResult,
    ExternalProcessStatus,
)
from app.external_tools.process_runner import ExternalProcessRunner
from app.external_tools.tool import BaseExternalTool
from app.external_tools.tool_policy import (
    ExternalToolInvocation,
    ToolPolicyDecision,
)
from app.external_tools.tool_request import ToolRequest
from app.external_tools.tool_request_builder import ExternalToolRequestBuilder
from app.external_tools.tool_result import (
    MAX_TOOL_EVIDENCE_ITEMS,
    MAX_TOOL_RESULT_TEXT_CHARACTERS,
    ExternalToolStatus,
    ToolEvidence,
    ToolResult,
)

TARGET_PATH_METADATA_KEY = "target_path"


class BaseFileExternalTool(BaseExternalTool):
    """Policyで許可された単一ファイル向け外部Toolを一度だけ実行する。"""

    def __init__(
        self,
        *,
        request_builder: ExternalToolRequestBuilder,
        process_runner: ExternalProcessRunner,
    ) -> None:
        self._request_builder = request_builder
        self._process_runner = process_runner

    def execute(self, request: ToolRequest) -> ToolResult:
        target = request.metadata.get(TARGET_PATH_METADATA_KEY)
        if request.working_directory is None or not isinstance(target, Path):
            return self._not_run("解析対象パスまたは作業ディレクトリが指定されていません。")
        if not target.is_absolute():
            return self._not_run("解析対象パスは絶対パスで指定してください。")

        evaluation = self._request_builder.build(
            ExternalToolInvocation(
                tool_type=self.tool_type,
                arguments=self._arguments(target),
                working_directory=request.working_directory,
            )
        )
        if evaluation.decision is ToolPolicyDecision.DENY:
            return ToolResult(
                tool_type=self.tool_type,
                status=ExternalToolStatus.SKIPPED,
                summary="外部Toolの実行はPolicyにより拒否されました。",
                stdout="",
                stderr="",
                exit_code=None,
                evidence=(),
                error_message=evaluation.message[:MAX_TOOL_RESULT_TEXT_CHARACTERS],
            )

        process_request = evaluation.process_request
        if process_request is None:
            return self._not_run("許可済みProcessRequestを生成できませんでした。")
        return self._to_tool_result(self._process_runner.run(process_request))

    @abstractmethod
    def _arguments(self, target: Path) -> tuple[str, ...]:
        raise NotImplementedError

    def _not_run(self, message: str) -> ToolResult:
        return ToolResult(
            tool_type=self.tool_type,
            status=self._not_run_status(),
            summary=message[:MAX_TOOL_RESULT_TEXT_CHARACTERS],
            stdout="",
            stderr="",
            exit_code=None,
            evidence=(),
            error_message=None,
        )

    def _not_run_status(self) -> ExternalToolStatus:
        return ExternalToolStatus.NOT_RUN

    def _to_tool_result(self, result: ExternalProcessResult) -> ToolResult:
        status = self._tool_status(result)
        return ToolResult(
            tool_type=self.tool_type,
            status=status,
            summary=self._summary_for_result(result, status),
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            evidence=self._evidence(result),
            error_message=(
                result.error_message[:MAX_TOOL_RESULT_TEXT_CHARACTERS]
                if result.error_message is not None
                else None
            ),
        )

    def _summary_for_result(
        self,
        result: ExternalProcessResult,
        status: ExternalToolStatus,
    ) -> str:
        return self._summary(status)

    def _tool_status(self, result: ExternalProcessResult) -> ExternalToolStatus:
        if result.status is ExternalProcessStatus.REJECTED:
            return ExternalToolStatus.SKIPPED
        if (
            result.status is ExternalProcessStatus.COMPLETED
            and result.exit_code == 0
        ):
            return ExternalToolStatus.COMPLETED
        return ExternalToolStatus.FAILED

    def _summary(self, status: ExternalToolStatus) -> str:
        if status is ExternalToolStatus.COMPLETED:
            return f"{self.tool_type.value}の解析が完了しました。"
        if status is ExternalToolStatus.SKIPPED:
            return f"{self.tool_type.value}の解析は実行されませんでした。"
        return f"{self.tool_type.value}の解析に失敗しました。"

    def _evidence(self, result: ExternalProcessResult) -> tuple[ToolEvidence, ...]:
        evidence: list[ToolEvidence] = []
        for stream_name, content in (("stdout", result.stdout), ("stderr", result.stderr)):
            for line in content.splitlines():
                detail = line.strip()
                if not detail:
                    continue
                evidence.append(
                    ToolEvidence(
                        source=self._evidence_source(stream_name),
                        detail=detail[:MAX_TOOL_RESULT_TEXT_CHARACTERS],
                        confidence=self._evidence_confidence(),
                    )
                )
                if len(evidence) == MAX_TOOL_EVIDENCE_ITEMS:
                    return tuple(evidence)
        return tuple(evidence)

    def _evidence_source(self, stream_name: str) -> str:
        return f"{self.tool_type.value}:{stream_name}"

    def _evidence_confidence(self) -> int | None:
        return None


class BaseBinaryInspectionTool(BaseFileExternalTool):
    """読み取り専用バイナリToolに共通する結果変換を提供する。"""

    @property
    @abstractmethod
    def completed_summary(self) -> str:
        raise NotImplementedError

    def _tool_status(self, result: ExternalProcessResult) -> ExternalToolStatus:
        if result.status is ExternalProcessStatus.COMPLETED:
            return ExternalToolStatus.COMPLETED
        return super()._tool_status(result)

    def _summary(self, status: ExternalToolStatus) -> str:
        if status is ExternalToolStatus.COMPLETED:
            return self.completed_summary
        return super()._summary(status)

    def _evidence_source(self, stream_name: str) -> str:
        return f"{self.tool_type.value}.{stream_name}"

    def _evidence_confidence(self) -> int | None:
        return 70
