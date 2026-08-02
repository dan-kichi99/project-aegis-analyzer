from pathlib import Path

from app.external_tools.tool import ExternalToolType
from app.external_tools.tool_adapter import BaseBinaryInspectionTool


class ReadelfTool(BaseBinaryInspectionTool):
    @property
    def tool_type(self) -> ExternalToolType:
        return ExternalToolType.READELF

    @property
    def completed_summary(self) -> str:
        return "readelfによる静的構造解析を実行しました。"

    def _arguments(self, target: Path) -> tuple[str, ...]:
        return ("-W", "-h", "-l", "-S", "-s", str(target))
