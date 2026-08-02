from pathlib import Path

from app.external_tools.tool import ExternalToolType
from app.external_tools.tool_policy import AllowedTool


class ExternalToolRegistry:
    def __init__(
        self,
        tools: tuple[AllowedTool, ...],
        allowed_working_root: Path,
    ) -> None:
        if not isinstance(allowed_working_root, Path) or not allowed_working_root.is_absolute():
            raise ValueError("allowed_working_rootは絶対Pathで指定してください。")
        if allowed_working_root.is_symlink():
            raise ValueError("allowed_working_rootにsymlinkは指定できません。")
        if not allowed_working_root.exists() or not allowed_working_root.is_dir():
            raise ValueError("allowed_working_rootは存在するディレクトリが必要です。")
        registered: dict[ExternalToolType, AllowedTool] = {}
        executable_paths: set[Path] = set()
        for tool in tools:
            if tool.tool_type is ExternalToolType.CUSTOM:
                raise ValueError("CUSTOM Toolは登録できません。")
            if tool.tool_type in registered:
                raise ValueError(f"ToolType「{tool.tool_type.value}」が重複しています。")
            executable = tool.executable
            if executable.is_symlink():
                raise ValueError("Tool executableにsymlinkは指定できません。")
            if not executable.exists() or not executable.is_file():
                raise ValueError("Tool executableは存在するファイルが必要です。")
            resolved = executable.resolve()
            if resolved in executable_paths:
                raise ValueError("同じexecutableを複数Toolへ登録できません。")
            executable_paths.add(resolved)
            registered[tool.tool_type] = tool
        self._tools = tuple(tools)
        self._registered = registered
        self._allowed_working_root = allowed_working_root.resolve()

    @property
    def tools(self) -> tuple[AllowedTool, ...]:
        return self._tools

    @property
    def allowed_working_root(self) -> Path:
        return self._allowed_working_root

    def get(self, tool_type: ExternalToolType) -> AllowedTool | None:
        return self._registered.get(tool_type)

    def is_registered(self, tool_type: ExternalToolType) -> bool:
        return tool_type in self._registered
