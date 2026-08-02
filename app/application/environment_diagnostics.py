import importlib
import os
import platform
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from app.application.environment_diagnostics_result import (
    DiagnosticStatus,
    DiagnosticTargetType,
    EnvironmentDiagnosticItem,
    EnvironmentDiagnosticsResult,
)

DEFAULT_TOOL_NAMES = (
    "strings",
    "file",
    "exiftool",
    "readelf",
    "objdump",
    "nm",
    "binwalk",
)
KNOWN_NAMES = frozenset(("python", "tkinter", "openai_configuration", *DEFAULT_TOOL_NAMES))


class EnvironmentDiagnostics:
    def __init__(
        self,
        *,
        tool_names: tuple[str, ...] = DEFAULT_TOOL_NAMES,
        required_names: tuple[str, ...] = ("python", "tkinter"),
        which: Callable[[str], str | None] = shutil.which,
        getenv: Callable[[str], str | None] = os.getenv,
        import_module: Callable[[str], object] = importlib.import_module,
        access: Callable[[Path, int], bool] = os.access,
        python_executable: str = sys.executable,
        python_version_info: object = sys.version_info,
        platform_name: str | None = None,
    ) -> None:
        self._validate_names(tool_names, "tool_names", 20)
        if any(name not in DEFAULT_TOOL_NAMES for name in tool_names):
            raise ValueError("未対応のTool名は診断できません。")
        self._validate_names(required_names, "required_names", 20)
        if any(name not in KNOWN_NAMES for name in required_names):
            raise ValueError("required_namesに未対応の名前があります。")
        self._tool_names = tool_names
        self._required_names = required_names
        self._which = which
        self._getenv = getenv
        self._import_module = import_module
        self._access = access
        self._python_executable = python_executable
        self._python_version_info = python_version_info
        self._platform_name = platform_name if platform_name is not None else platform.system()

    def run(self) -> EnvironmentDiagnosticsResult:
        items = (
            self._safe_diagnostic(self._diagnose_python, DiagnosticTargetType.PYTHON, "python"),
            self._safe_diagnostic(self._diagnose_tkinter, DiagnosticTargetType.TKINTER, "tkinter"),
            self._safe_diagnostic(
                self._diagnose_openai,
                DiagnosticTargetType.OPENAI_CONFIGURATION,
                "openai_configuration",
            ),
            *(
                self._safe_diagnostic(
                    lambda name=name: self._diagnose_tool(name),
                    DiagnosticTargetType.EXTERNAL_TOOL,
                    name,
                )
                for name in self._tool_names
            ),
        )
        available = sum(item.available for item in items)
        by_name = {item.name: item for item in items}
        required_available = all(
            name in by_name and by_name[name].available for name in self._required_names
        )
        executable_name = Path(self._python_executable).name if self._python_executable else ""
        return EnvironmentDiagnosticsResult(
            items,
            required_available,
            available,
            len(items) - available,
            self._platform_name[:100],
            executable_name[:200],
        )

    def _diagnose_python(self) -> EnvironmentDiagnosticItem:
        raw_path = self._python_executable
        if not raw_path:
            return self._unavailable(
                DiagnosticTargetType.PYTHON,
                "python",
                DiagnosticStatus.NOT_FOUND,
                "Python実行ファイルを確認できません。",
            )
        path = Path(raw_path)
        if not path.is_absolute() or not path.exists() or not path.is_file():
            return self._unavailable(
                DiagnosticTargetType.PYTHON,
                "python",
                DiagnosticStatus.INVALID_PATH,
                "Python実行ファイルのPathが不正です。",
            )
        if path.is_symlink():
            return self._unavailable(
                DiagnosticTargetType.PYTHON,
                "python",
                DiagnosticStatus.SYMLINK_REJECTED,
                "Python実行ファイルのシンボリックリンクは利用できません。",
            )
        version = ".".join(
            str(value)
            for value in (
                self._python_version_info.major,
                self._python_version_info.minor,
                self._python_version_info.micro,
            )
        )
        return EnvironmentDiagnosticItem(
            DiagnosticTargetType.PYTHON,
            "python",
            DiagnosticStatus.AVAILABLE,
            True,
            "Python実行環境を確認しました。",
            version=version,
        )

    def _diagnose_tkinter(self) -> EnvironmentDiagnosticItem:
        try:
            module = self._import_module("tkinter")
        except (ImportError, ModuleNotFoundError):
            return self._unavailable(
                DiagnosticTargetType.TKINTER,
                "tkinter",
                DiagnosticStatus.NOT_FOUND,
                "Tkinterを読み込めません。",
            )
        version_value = getattr(module, "TkVersion", None)
        version = str(version_value)[:200] if version_value is not None else None
        return EnvironmentDiagnosticItem(
            DiagnosticTargetType.TKINTER,
            "tkinter",
            DiagnosticStatus.AVAILABLE,
            True,
            "Tkinterモジュールを確認しました。画面生成は行っていません。",
            version=version,
        )

    def _diagnose_openai(self) -> EnvironmentDiagnosticItem:
        value = self._getenv("OPENAI_API_KEY")
        if value is None or not value.strip():
            return self._unavailable(
                DiagnosticTargetType.OPENAI_CONFIGURATION,
                "openai_configuration",
                DiagnosticStatus.NOT_CONFIGURED,
                "OpenAI API設定が見つかりません。",
            )
        return EnvironmentDiagnosticItem(
            DiagnosticTargetType.OPENAI_CONFIGURATION,
            "openai_configuration",
            DiagnosticStatus.AVAILABLE,
            True,
            "OpenAI API設定が存在します。接続確認は行っていません。",
        )

    def _diagnose_tool(self, name: str) -> EnvironmentDiagnosticItem:
        raw_path = self._which(name)
        if raw_path is None:
            return self._unavailable(
                DiagnosticTargetType.EXTERNAL_TOOL,
                name,
                DiagnosticStatus.NOT_FOUND,
                "実行ファイルがPATH上に見つかりません。",
            )
        path = Path(raw_path)
        if not path.is_absolute() or not path.exists() or not path.is_file():
            return self._unavailable(
                DiagnosticTargetType.EXTERNAL_TOOL,
                name,
                DiagnosticStatus.INVALID_PATH,
                "実行ファイルのPathが不正です。",
            )
        if path.is_symlink():
            return self._unavailable(
                DiagnosticTargetType.EXTERNAL_TOOL,
                name,
                DiagnosticStatus.SYMLINK_REJECTED,
                "シンボリックリンクは利用できません。",
            )
        if not self._is_executable(path):
            return self._unavailable(
                DiagnosticTargetType.EXTERNAL_TOOL,
                name,
                DiagnosticStatus.NOT_EXECUTABLE,
                "実行可能性を確認できません。",
            )
        return EnvironmentDiagnosticItem(
            DiagnosticTargetType.EXTERNAL_TOOL,
            name,
            DiagnosticStatus.AVAILABLE,
            True,
            "利用可能な実行ファイルを確認しました。実行は行っていません。",
            executable_path=path,
        )

    def _is_executable(self, path: Path) -> bool:
        if self._platform_name.casefold() == "windows":
            return path.suffix.casefold() in {".exe", ".com", ".bat", ".cmd"} or self._access(
                path, os.X_OK
            )
        return self._access(path, os.X_OK)

    def _safe_diagnostic(
        self,
        diagnostic: Callable[[], EnvironmentDiagnosticItem],
        target_type: DiagnosticTargetType,
        name: str,
    ) -> EnvironmentDiagnosticItem:
        try:
            return diagnostic()
        except Exception:  # noqa: BLE001 - 項目単位で固定ERRORへ変換
            return self._unavailable(
                target_type,
                name,
                DiagnosticStatus.ERROR,
                "診断中にエラーが発生しました。",
            )

    @staticmethod
    def _unavailable(
        target_type: DiagnosticTargetType,
        name: str,
        status: DiagnosticStatus,
        message: str,
    ) -> EnvironmentDiagnosticItem:
        return EnvironmentDiagnosticItem(target_type, name, status, False, message)

    @staticmethod
    def _validate_names(values: tuple[str, ...], label: str, maximum: int) -> None:
        if not isinstance(values, tuple):
            raise TypeError(f"{label}はtupleで指定してください。")
        if len(values) > maximum:
            raise ValueError(f"{label}は最大{maximum}件です。")
        if len(values) != len(set(values)):
            raise ValueError(f"{label}に重複があります。")
        for value in values:
            if not isinstance(value, str) or not value or not value.strip():
                raise ValueError(f"{label}に空の名前は指定できません。")
            if "\0" in value:
                raise ValueError(f"{label}にNUL文字は指定できません。")
