from pathlib import Path

from app.external_tools.tool import ExternalToolType
from app.external_tools.tool_adapter import BaseBinaryInspectionTool


class ObjdumpTool(BaseBinaryInspectionTool):
    @property
    def tool_type(self) -> ExternalToolType:
        return ExternalToolType.OBJDUMP

    @property
    def completed_summary(self) -> str:
        return "objdumpによるヘッダー・逆アセンブル解析を実行しました。"

    def _arguments(self, target: Path) -> tuple[str, ...]:
        return ("-d", "-f", "-h", str(target))
