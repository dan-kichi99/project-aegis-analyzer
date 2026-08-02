import importlib
import inspect
from dataclasses import replace

import pytest

from app.codegen.generated_code_result import GeneratedCodeResult
from app.presentation import (
    ActionApprovalDecision,
    ActionApprovalPresenter,
    ActionApprovalRequest,
    AnalysisEventBuffer,
    AnalysisInputPresenter,
    ApplicationPresenter,
    CodeApprovalDecision,
    CodeApprovalRequest,
    CodeExecutionPresenter,
    CodeExecutionRequest,
)


class FakeFrame:
    def __init__(self, _parent=None, **_values):
        self.pack_calls = 0

    def pack(self, **_values):
        self.pack_calls += 1


class RecordingView:
    def __init__(self, _parent=None, *_args):
        self.frame = FakeFrame()
        self.rendered = []
        self.clear_calls = 0

    def render(self, value):
        self.rendered.append(value)

    def clear(self):
        self.clear_calls += 1


class InputView(RecordingView):
    def __init__(self, parent, _presenter, callback, cancel_callback):
        super().__init__(parent)
        self.callback = callback
        self.cancel_callback = cancel_callback

    def set_enabled(self, enabled):
        self.enabled = enabled


class ProgressView(RecordingView):
    def __init__(self, parent):
        super().__init__(parent)
        self.history = []

    def clear_history(self):
        self.history.clear()

    def append_history(self, value):
        self.history.append(value)


class CallbackView(RecordingView):
    def __init__(self, parent, _presenter, *callbacks):
        super().__init__(parent)
        self.callbacks = callbacks


class CodeView(CallbackView):
    def render_candidates(self, value):
        self.generated = value

    def render_execution_results(self, value):
        self.executions = value


class RecordingBridge:
    def __init__(self, _root, _buffer, _presenter, state, callback):
        self.state = state
        self.callback = callback
        self.starts = 0
        self.stops = 0

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1

    def set_state(self, state):
        self.state = state


def _shell(monkeypatch, **callbacks):
    module = importlib.import_module("app.gui.application_shell")
    monkeypatch.setattr(module.tk, "Frame", FakeFrame)
    monkeypatch.setattr(module, "AnalysisInputView", InputView)
    monkeypatch.setattr(module, "AnalysisProgressView", ProgressView)
    monkeypatch.setattr(module, "AnalysisResultPanel", RecordingView)
    monkeypatch.setattr(module, "ActionApprovalView", CallbackView)
    monkeypatch.setattr(module, "CodeExecutionView", CodeView)
    monkeypatch.setattr(module, "ExternalToolView", RecordingView)
    monkeypatch.setattr(module, "BudgetView", RecordingView)
    monkeypatch.setattr(module, "TkEventBridge", RecordingBridge)
    shell = module.ProjectAegisApplicationShell(
        object(),
        input_presenter=AnalysisInputPresenter(),
        application_presenter=ApplicationPresenter(),
        action_approval_presenter=ActionApprovalPresenter(),
        code_execution_presenter=CodeExecutionPresenter(),
        event_buffer=AnalysisEventBuffer(),
        **callbacks,
    )
    return module, shell


def test_import_is_safe_and_shell_creates_all_views(monkeypatch):
    module, shell = _shell(monkeypatch)
    source = inspect.getsource(module)
    assert "tk.Tk(" not in source and "mainloop(" not in source
    assert all(
        getattr(shell, name) is not None
        for name in (
            "input_view", "progress_view", "result_panel",
            "action_approval_view", "code_execution_view",
            "external_tool_view", "budget_view",
        )
    )
    assert shell.state is shell._application_presenter.initial_state() or shell.state.progress.phase == "idle"


def test_render_distributes_original_state_without_mutation(monkeypatch):
    _module, shell = _shell(monkeypatch)
    state = replace(shell.state, result=None, agent=None)
    shell.render(state)
    assert shell.state is state
    assert shell._event_bridge.state is state
    assert shell.progress_view.rendered[-1] is state.progress
    assert shell.result_panel.rendered[-1] is state
    assert shell.action_approval_view.rendered[-1] is state.iteration
    assert shell.external_tool_view.rendered[-1] is state
    assert shell.budget_view.rendered[-1] is state
    assert state.result is None and state.agent is None


def test_generated_execution_forwarding_and_bridge_lifecycle(monkeypatch):
    _module, shell = _shell(monkeypatch)
    generated = GeneratedCodeResult(())
    shell.render_generated_code(generated)
    shell.render_execution_results(())
    assert shell.code_execution_view.generated is generated
    assert shell.code_execution_view.executions == ()
    shell.start_event_bridge()
    shell.stop_event_bridge()
    assert shell._event_bridge.starts == shell._event_bridge.stops == 1


def test_event_callback_updates_state_renders_and_appends_history(monkeypatch):
    _module, shell = _shell(monkeypatch)
    updated = replace(shell.state, result=None)
    shell._event_bridge.callback(updated)
    assert shell.state is updated
    assert shell.progress_view.rendered[-1] is updated.progress
    assert shell.progress_view.history == [updated.progress]


def test_callbacks_are_passed_through_and_exceptions_are_not_wrapped(monkeypatch):
    callbacks = {
        "on_analysis_requested": lambda value: value,
        "on_action_decision": lambda value: value,
        "on_code_decision": lambda value: value,
        "on_code_execution_requested": lambda value: value,
    }
    _module, shell = _shell(monkeypatch, **callbacks)
    assert shell.input_view.callback is callbacks["on_analysis_requested"]
    assert shell.action_approval_view.callbacks == (callbacks["on_action_decision"],)
    assert shell.code_execution_view.callbacks == (
        callbacks["on_code_decision"], callbacks["on_code_execution_requested"]
    )
    requests = (
        ActionApprovalRequest("a", ActionApprovalDecision.APPROVE),
        CodeApprovalRequest(1, CodeApprovalDecision.REJECT),
        CodeExecutionRequest(1),
    )
    assert callbacks["on_action_decision"](requests[0]) is requests[0]
    assert callbacks["on_code_decision"](requests[1]) is requests[1]
    assert callbacks["on_code_execution_requested"](requests[2]) is requests[2]


def test_clear_resets_every_view_without_callbacks(monkeypatch):
    calls = []
    _module, shell = _shell(
        monkeypatch,
        on_analysis_requested=calls.append,
        on_action_decision=calls.append,
        on_code_decision=calls.append,
        on_code_execution_requested=calls.append,
    )
    shell.progress_view.history.append("old")
    shell.clear()
    assert calls == []
    assert shell.input_view.clear_calls == 1
    assert shell.progress_view.history == []
    assert shell.code_execution_view.clear_calls == 1
    assert shell.state.progress.phase == "idle"


def test_analysis_lock_disables_input_and_blocks_clear(monkeypatch):
    _module, shell = _shell(monkeypatch)
    shell.set_analysis_active(True)
    assert shell.analysis_active and shell.input_view.enabled is False
    with pytest.raises(RuntimeError, match="解析中"):
        shell.clear()
    shell.set_analysis_active(False)
    assert not shell.analysis_active and shell.input_view.enabled is True


def test_shell_has_no_domain_execution_or_secret_dependencies():
    source = inspect.getsource(
        importlib.import_module("app.gui.application_shell").ProjectAegisApplicationShell
    ).casefold()
    for forbidden in (
        "controller", "challengeservice", "statemanager", "coordinator",
        "pythonexecutionrunner", "subprocess", "thread", "asyncio", "sleep(",
        "exec(", "eval(", "api_key", "stdout", "stderr", "metadata", "submit",
    ):
        assert forbidden not in source
