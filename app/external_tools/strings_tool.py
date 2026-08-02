from pathlib import Path

from app.external_tools.tool import ExternalToolType
from app.external_tools.tool_adapter import BaseFileExternalTool


class StringsTool(BaseFileExternalTool):
    @property
    def tool_type(self) -> ExternalToolType:
        return ExternalToolType.STRINGS

    def _arguments(self, target: Path) -> tuple[str, ...]:
        return (str(target),)
