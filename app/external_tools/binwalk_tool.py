from pathlib import Path

from app.external_tools.binwalk_parser import BinwalkParser
from app.external_tools.process_result import ExternalProcessResult
from app.external_tools.tool import ExternalToolType
from app.external_tools.tool_adapter import BaseBinaryInspectionTool
from app.external_tools.tool_result import (
    MAX_TOOL_EVIDENCE_ITEMS,
    MAX_TOOL_RESULT_TEXT_CHARACTERS,
    ExternalToolStatus,
    ToolEvidence,
)


class BinwalkTool(BaseBinaryInspectionTool):
    def __init__(self, *, request_builder, process_runner) -> None:
        super().__init__(
            request_builder=request_builder,
            process_runner=process_runner,
        )
        self._parser = BinwalkParser()

    @property
    def tool_type(self) -> ExternalToolType:
        return ExternalToolType.BINWALK

    @property
    def completed_summary(self) -> str:
        return "binwalkによるシグネチャ解析を実行しました。"

    def _arguments(self, target: Path) -> tuple[str, ...]:
        return ("--signature", str(target))

    def _not_run_status(self) -> ExternalToolStatus:
        return ExternalToolStatus.SKIPPED

    def _summary_for_result(
        self,
        result: ExternalProcessResult,
        status: ExternalToolStatus,
    ) -> str:
        if status is ExternalToolStatus.COMPLETED and result.exit_code != 0:
            return "binwalkは実行されましたが、正常終了しませんでした。"
        return super()._summary_for_result(result, status)

    def _evidence(self, result: ExternalProcessResult) -> tuple[ToolEvidence, ...]:
        analysis = self._parser.parse(result.stdout)
        evidence: list[ToolEvidence] = []
        entry_limit = MAX_TOOL_EVIDENCE_ITEMS - int(result.stdout_truncated)
        for entry in analysis.entries[:entry_limit]:
            detail = (
                f"offset={entry.decimal_offset} "
                f"({entry.hexadecimal_offset}): {entry.description}"
            )
            evidence.append(
                ToolEvidence(
                    source="binwalk.signature",
                    detail=detail[:MAX_TOOL_RESULT_TEXT_CHARACTERS],
                    confidence=70,
                )
            )
        if result.stdout_truncated:
            evidence.append(
                ToolEvidence(
                    source="binwalk.warning",
                    detail="binwalkの標準出力は上限により省略されています。",
                    confidence=None,
                )
            )
        for line in result.stderr.splitlines():
            detail = line.strip()
            if detail and len(evidence) < MAX_TOOL_EVIDENCE_ITEMS:
                evidence.append(
                    ToolEvidence(
                        source="binwalk.stderr",
                        detail=detail[:MAX_TOOL_RESULT_TEXT_CHARACTERS],
                        confidence=70,
                    )
                )
        return tuple(evidence)
