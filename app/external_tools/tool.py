from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.external_tools.tool_request import ToolRequest
    from app.external_tools.tool_result import ToolResult


class ExternalToolType(str, Enum):
    STRINGS = "strings"
    FILE = "file"
    EXIFTOOL = "exiftool"
    BINWALK = "binwalk"
    READELF = "readelf"
    OBJDUMP = "objdump"
    NM = "nm"
    OPENSSL = "openssl"
    CUSTOM = "custom"


class BaseExternalTool(ABC):
    """外部ツール連携が実装する共通契約。"""

    @property
    @abstractmethod
    def tool_type(self) -> ExternalToolType:
        raise NotImplementedError

    @abstractmethod
    def execute(self, request: ToolRequest) -> ToolResult:
        raise NotImplementedError
