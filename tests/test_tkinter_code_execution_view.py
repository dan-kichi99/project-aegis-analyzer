import importlib
import inspect
from dataclasses import replace

import pytest

from app.codegen.code_safety_result import CodeRiskLevel, CodeSafetyResult
from app.codegen.generated_code_result import (
    GeneratedCode,
    GeneratedCodeLanguage,
    GeneratedCodeResult,
    GeneratedCodeStatus,
)
from app.execution.execution_analysis_result import (
    ExecutionAnalysisResult,
    ExecutionFlagCandidate,
    ExecutionOutputSource,
)
from app.execution.execution_result import ExecutionStatus, PythonExecutionResult
from app.presentation import (
    CodeApprovalDecision,
    CodeApprovalRequest,
    CodeExecutionPresenter,
    CodeExecutionRequest,
)


class FakeWidget:
    def __init__(self, _parent=None, **values):
        self.values = values
        self.items = []
        self.content = ""
        self.selection = ()
        self.binding = None

    def pack(self, **_values):
        return None

    def configure(self, **values):
        self.values.update(values)

    def bind(self, _event, callback):
        self.binding = callback

    def delete(self, *_values):
        self.items.clear()
        self.content = ""

    def insert(self, _position, value):
        if "state" in self.values:
            self.content += value
        else:
            self.items.append(value)

    def curselection(self):
        return self.selection

    def invoke(self):
        return self.values["command"]()


def _code(risk=CodeRiskLevel.LOW, status=GeneratedCodeStatus.REVIEW_REQUIRED):
    return GeneratedCode(
        GeneratedCodeLanguage.PYTHON,
        "print('unchanged')",
        "目的",
        3,
        status,
        CodeSafetyResult(True, risk, ()),
    )


def _analysis():
    execution = PythonExecutionResult(
        ExecutionStatus.TIMED_OUT,
        True,
        "FLAG{output}",
        "partial error",
        None,
        True,
        0.5,
        None,
        "timeout",
        True,
        True,
    )
    flag = ExecutionFlagCandidate("FLAG{output}", ExecutionOutputSource.STDOUT, 0)
    return ExecutionAnalysisResult(execution, (flag,), flag.flag, False)


def _view(monkeypatch, approval=None, execution=None):
    module = importlib.import_module("app.gui.code_execution_view")
    for name in ("Frame", "Label", "Listbox", "Text", "Button"):
        monkeypatch.setattr(module.tk, name, FakeWidget)
    return module, module.CodeExecutionView(
        object(), CodeExecutionPresenter(), approval, execution
    )


def _select(view, index=0):
    view.candidate_list.selection = (index,)
    view.candidate_list.binding(None)


def test_import_is_safe_without_root_mainloop_or_execution():
    module = importlib.import_module("app.gui.code_execution_view")
    source = inspect.getsource(module)
    assert "tk.Tk(" not in source and "mainloop(" not in source


def test_none_clear_and_candidate_details_read_only(monkeypatch):
    _module, view = _view(monkeypatch)
    view.render_candidates(None)
    assert view.candidate_list.items == []
    assert view.approve_button.values["state"] == "disabled"
    view.render_candidates(GeneratedCodeResult((_code(),)))
    _select(view)
    assert view.candidate_list.items == [
        "[3] python / review_required / low / 目的"
    ]
    assert view.code_text.content == "print('unchanged')"
    assert view.code_text.values["state"] == "disabled"
    assert view.risk_label.values["text"] == "危険度：low"
    view.clear()
    assert view.candidate_list.items == [] and view.code_text.content == ""


@pytest.mark.parametrize(
    ("risk", "approve"),
    ((CodeRiskLevel.LOW, "normal"), (CodeRiskLevel.MEDIUM, "normal"),
     (CodeRiskLevel.HIGH, "disabled"), (CodeRiskLevel.BLOCKED, "disabled")),
)
def test_review_button_states_by_risk(monkeypatch, risk, approve):
    _module, view = _view(monkeypatch)
    view.render_candidates(GeneratedCodeResult((_code(risk),)))
    _select(view)
    assert view.approve_button.values["state"] == approve
    assert view.reject_button.values["state"] == "normal"
    assert view.defer_button.values["state"] == "normal"
    assert view.execute_button.values["state"] == "disabled"


def test_approved_low_only_enables_execution(monkeypatch):
    _module, view = _view(monkeypatch)
    view.render_candidates(
        GeneratedCodeResult((_code(status=GeneratedCodeStatus.APPROVED),))
    )
    _select(view)
    assert view.execute_button.values["state"] == "normal"
    assert view.approve_button.values["state"] == "disabled"
    assert view.reject_button.values["state"] == "disabled"
    assert view.defer_button.values["state"] == "disabled"


@pytest.mark.parametrize(
    ("button", "decision"),
    (("approve_button", CodeApprovalDecision.APPROVE),
     ("reject_button", CodeApprovalDecision.REJECT),
     ("defer_button", CodeApprovalDecision.DEFER)),
)
def test_approval_callbacks_once_without_state_change(monkeypatch, button, decision):
    calls = []
    _module, view = _view(monkeypatch, calls.append)
    view.render_candidates(GeneratedCodeResult((_code(),)))
    _select(view)
    getattr(view, button).invoke()
    assert calls == [CodeApprovalRequest(3, decision)]
    assert view.state.selected_candidate.status == "review_required"
    assert view.code_text.content == "print('unchanged')"


def test_execution_callback_once_and_callback_errors_propagate(monkeypatch):
    calls = []
    _module, view = _view(monkeypatch, execution=calls.append)
    view.render_candidates(
        GeneratedCodeResult((_code(status=GeneratedCodeStatus.APPROVED),))
    )
    _select(view)
    view.execute_button.invoke()
    assert calls == [CodeExecutionRequest(3)]

    def fail(_request):
        raise RuntimeError("callback failure")

    _module, failed = _view(monkeypatch, approval=fail)
    failed.render_candidates(GeneratedCodeResult((_code(),)))
    _select(failed)
    with pytest.raises(RuntimeError, match="callback failure"):
        failed.approve_button.invoke()


def test_invalid_button_callback_is_not_sent(monkeypatch):
    calls = []
    _module, view = _view(monkeypatch, calls.append, calls.append)
    view.render_candidates(GeneratedCodeResult((_code(CodeRiskLevel.HIGH),)))
    _select(view)
    view.approve_button.invoke()
    view.execute_button.invoke()
    assert calls == []


def test_execution_output_flags_and_warnings_are_read_only(monkeypatch):
    _module, view = _view(monkeypatch)
    view.render_candidates(GeneratedCodeResult((_code(),)))
    view.render_execution_results((_analysis(),))
    assert view.execution_status_label.values["text"] == "実行状態：timed_out"
    assert view.stdout_text.content == "FLAG{output}"
    assert view.stderr_text.content == "partial error"
    assert view.stdout_text.values["state"] == "disabled"
    assert view.stderr_text.values["state"] == "disabled"
    assert view.flag_candidates_list.items == ["FLAG{output}"]
    assert view.primary_flag_label.values["text"] == "主要Flag候補：FLAG{output}"
    warning = view.execution_warning_label.values["text"]
    assert "候補" in warning and "途中出力" in warning and "省略" in warning
    assert "正解Flag" not in warning


def test_single_result_for_candidate_b_uses_explicit_source_index(monkeypatch):
    _module, view = _view(monkeypatch)
    first = replace(_code(), source_index=0)
    second = replace(_code(), source_index=1)
    view.render_candidates(GeneratedCodeResult((first, second)))
    view.render_execution_results((replace(_analysis(), source_index=1),))
    assert view.execution_result_list.items == ["[1] timed_out"]
    assert "[0]" not in view.execution_result_list.items[0]


def test_view_has_no_execution_or_approval_service_dependencies():
    source = inspect.getsource(
        importlib.import_module("app.gui.code_execution_view").CodeExecutionView
    ).casefold()
    for forbidden in (
        "codeapprovalservice", "pythonexecutionrunner", "executionresultanalyzer",
        "subprocess", "exec(", "eval(", "compile(", "thread", "asyncio",
        "sleep(", "controller", "challengeservice", "api_key", "metadata",
    ):
        assert forbidden not in source
