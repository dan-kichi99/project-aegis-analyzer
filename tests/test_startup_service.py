from dataclasses import FrozenInstanceError

import pytest

from app.application.environment_diagnostics_result import (
    DiagnosticStatus,
    DiagnosticTargetType,
    EnvironmentDiagnosticItem,
    EnvironmentDiagnosticsResult,
)
from app.application.startup_result import StartupMode, StartupResult, StartupStatus
from app.application.startup_service import StartupService


class FakeDiagnostics:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    def run(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def _item(name, target, available=True):
    return EnvironmentDiagnosticItem(
        target,
        name,
        DiagnosticStatus.AVAILABLE if available else DiagnosticStatus.NOT_FOUND,
        available,
        "固定診断メッセージ",
    )


def _diagnostics(*, python=True, tkinter=True, openai=True, tool=True):
    items = (
        _item("python", DiagnosticTargetType.PYTHON, python),
        _item("tkinter", DiagnosticTargetType.TKINTER, tkinter),
        _item("openai_configuration", DiagnosticTargetType.OPENAI_CONFIGURATION, openai),
        _item("strings", DiagnosticTargetType.EXTERNAL_TOOL, tool),
    )
    available = sum(item.available for item in items)
    return EnvironmentDiagnosticsResult(
        items,
        python and tkinter,
        available,
        len(items) - available,
        "Windows",
        "python.exe",
    )


def test_startup_enums_and_dto_are_frozen_slotted_and_validate_exit_code():
    result = StartupResult(StartupMode.CLI, StartupStatus.READY, "ready", None, 0)
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.exit_code = 1  # type: ignore[misc]
    with pytest.raises(TypeError):
        StartupResult(StartupMode.CLI, StartupStatus.READY, "ready", None, True)
    with pytest.raises(ValueError):
        StartupResult(StartupMode.CLI, StartupStatus.READY, "", None, 0)


@pytest.mark.parametrize("mode", list(StartupMode))
def test_all_available_is_ready(mode):
    diagnostics = FakeDiagnostics(_diagnostics())
    result = StartupService(diagnostics=diagnostics).check(mode)
    assert result.status is StartupStatus.READY
    assert result.exit_code == 0
    assert diagnostics.calls == 1


def test_cli_does_not_require_tkinter():
    result = StartupService(
        diagnostics=FakeDiagnostics(_diagnostics(tkinter=False))
    ).check(StartupMode.CLI)
    assert result.status is StartupStatus.READY


@pytest.mark.parametrize("missing", ["openai", "tool"])
def test_optional_configuration_is_degraded_not_blocked(missing):
    values = {"openai": True, "tool": True}
    values[missing] = False
    result = StartupService(
        diagnostics=FakeDiagnostics(_diagnostics(**values))
    ).check(StartupMode.GUI)
    assert result.status is StartupStatus.DEGRADED
    assert result.exit_code == 0


def test_gui_without_tkinter_is_blocked_but_cli_remains_available():
    diagnostics = _diagnostics(tkinter=False)
    gui = StartupService(diagnostics=FakeDiagnostics(diagnostics)).check(StartupMode.GUI)
    cli = StartupService(diagnostics=FakeDiagnostics(diagnostics)).check(StartupMode.CLI)
    assert gui.status is StartupStatus.BLOCKED and gui.exit_code == 2
    assert cli.status is StartupStatus.READY and cli.exit_code == 0


def test_missing_python_blocks_every_mode():
    for mode in StartupMode:
        result = StartupService(
            diagnostics=FakeDiagnostics(_diagnostics(python=False))
        ).check(mode)
        assert result.status is StartupStatus.BLOCKED
        assert result.exit_code == 2


def test_diagnostic_failure_uses_fixed_message_without_secret():
    result = StartupService(
        diagnostics=FakeDiagnostics(error=RuntimeError("OPENAI_API_KEY_TEST_SECRET"))
    ).check(StartupMode.GUI)
    assert result.status is StartupStatus.FAILED
    assert result.exit_code == 1
    assert "OPENAI_API_KEY_TEST_SECRET" not in result.message
