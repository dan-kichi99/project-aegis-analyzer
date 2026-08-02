from app.application.environment_diagnostics import EnvironmentDiagnostics
from app.application.environment_diagnostics_result import DiagnosticStatus
from app.application.startup_result import (
    StartupMode,
    StartupResult,
    StartupStatus,
)


class StartupService:
    def __init__(self, *, diagnostics: EnvironmentDiagnostics) -> None:
        self._diagnostics = diagnostics

    def check(self, mode: StartupMode) -> StartupResult:
        if not isinstance(mode, StartupMode):
            raise TypeError("mode must be StartupMode.")
        try:
            diagnostics = self._diagnostics.run()
        except Exception:  # noqa: BLE001 - startup boundary uses a fixed safe result
            return StartupResult(
                mode,
                StartupStatus.FAILED,
                "環境診断を完了できませんでした。",
                None,
                1,
            )
        by_name = {item.name: item for item in diagnostics.items}
        python = by_name.get("python")
        tkinter = by_name.get("tkinter")
        if python is None or python.status is not DiagnosticStatus.AVAILABLE:
            return StartupResult(
                mode,
                StartupStatus.BLOCKED,
                "Python実行環境を確認できないため起動できません。",
                diagnostics,
                2,
            )
        if mode is StartupMode.GUI and (
            tkinter is None or tkinter.status is not DiagnosticStatus.AVAILABLE
        ):
            return StartupResult(
                mode,
                StartupStatus.BLOCKED,
                "Tkinterを利用できないためGUIを起動できません。",
                diagnostics,
                2,
            )
        optional_unavailable = any(
            not item.available
            for item in diagnostics.items
            if item.name not in {"python", "tkinter"}
        )
        if optional_unavailable:
            return StartupResult(
                mode,
                StartupStatus.DEGRADED,
                "一部の任意機能は利用できません。ローカル解析は起動できます。",
                diagnostics,
                0,
            )
        return StartupResult(
            mode,
            StartupStatus.READY,
            "起動に必要な環境を確認しました。",
            diagnostics,
            0,
        )
