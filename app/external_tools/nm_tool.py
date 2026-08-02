from pathlib import Path

from app.external_tools.tool import ExternalToolType
from app.external_tools.tool_adapter import BaseBinaryInspectionTool


class NmTool(BaseBinaryInspectionTool):
    @property
    def tool_type(self) -> ExternalToolType:
        return ExternalToolType.NM

    @property
    def completed_summary(self) -> str:
        return "nmによるシンボル解析を実行しました。"

    def _arguments(self, target: Path) -> tuple[str, ...]:
        return ("-C", "-n", str(target))
