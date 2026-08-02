import importlib
import inspect
from dataclasses import replace
from datetime import datetime, timezone

from app.application import ApplicationController
from app.codegen.code_safety_result import CodeRiskLevel, CodeSafetyResult
from app.codegen.generated_code_result import (
    GeneratedCode,
    GeneratedCodeLanguage,
    GeneratedCodeResult,
    GeneratedCodeStatus,
)
from app.events.analysis_event import AnalysisEvent, AnalysisEventType
from app.events.event_publisher import EventPublisher
from app.execution.execution_analysis_result import ExecutionAnalysisResult
from app.execution.execution_result import ExecutionStatus, PythonExecutionResult
from app.judge.judge_result import JudgeResult
from app.presentation import (
    ActionApprovalPresenter,
    ActionViewModel,
    AgentViewModel,
    AnalysisEventBuffer,
    AnalysisInputPresenter,
    ApplicationPresenter,
    BudgetViewModel,
    CodeExecutionPresenter,
    ExternalToolViewModel,
    IterationViewModel,
    ResultViewModel,
)


class FakeWidget:
    def __init__(self, _parent=None, **values):
        self.values = values
        self.items = []
        self.content = ""
        self.selection = ()
        self.binding = None
        self.start_calls = 0
        self.stop_calls = 0

    def pack(self, **_values):
        return None

    def configure(self, **values):
        self.values.update(values)

    def bind(self, _event, callback):
        self.binding = callback

    def get(self, *_values):
        return self.content

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

    def start(self):
        self.start_calls += 1

    def stop(self):
        self.stop_calls += 1


class FakeRoot(FakeWidget):
    def __init__(self):
        super().__init__()
        self.scheduled = []

    def after(self, milliseconds, callback):
        self.scheduled.append((milliseconds, callback))
        return f"after-{len(self.scheduled)}"

    def after_cancel(self, _identifier):
        return None


def _shell(monkeypatch, **callbacks):
    module_names = (
        "app.gui.application_shell", "app.gui.input_view", "app.gui.progress_view",
        "app.gui.result_view", "app.gui.agent_result_view",
        "app.gui.action_approval_view", "app.gui.code_execution_view",
        "app.gui.external_tool_view", "app.gui.budget_view",
    )
    modules = [importlib.import_module(name) for name in module_names]
    for module in modules:
        for name in ("Frame", "Label", "Listbox", "Text", "Button"):
            if hasattr(module.tk, name):
                monkeypatch.setattr(module.tk, name, FakeWidget)
    progress = importlib.import_module("app.gui.progress_view")
    monkeypatch.setattr(progress.ttk, "Progressbar", FakeWidget)
    buffer = AnalysisEventBuffer()
    shell = modules[0].ProjectAegisApplicationShell(
        FakeRoot(),
        input_presenter=AnalysisInputPresenter(),
        application_presenter=ApplicationPresenter(),
        action_approval_presenter=ActionApprovalPresenter(),
        code_execution_presenter=CodeExecutionPresenter(),
        event_buffer=buffer,
        **callbacks,
    )
    return shell, buffer


def _state(shell):
    result = ResultViewModel(
        True, "Rev", "answer", "FLAG{candidate}", 80, "reason", ("next",),
        "Flagは候補です。",
    )
    agent = AgentViewModel(
        "rev", ("rev",), "completed", 80, ("evidence",),
        ("FLAG{candidate}",), (), False,
    )
    action = ActionViewModel("action-1", "run_agent", "proposed", 90, "調査する", True)
    iteration = IterationViewModel("session", "active", 1, (action,), (), (), (), None)
    tool = ExternalToolViewModel(
        "strings", "completed", "sample.bin", "summary", 0,
        ("source: evidence",), False, None,
    )
    budget = BudgetViewModel(1, 5, 2, 10, 1, 5, 1, 5, 2, 10, 0, 5, 1, 10, 2.0, 60.0)
    return replace(shell.state, result=result, agent=agent, iteration=iteration, external_tools=(tool,), budget=budget)


def _code(source_index, status=GeneratedCodeStatus.REVIEW_REQUIRED):
    return GeneratedCode(
        GeneratedCodeLanguage.PYTHON, f"print({source_index})", "purpose",
        source_index, status, CodeSafetyResult(True, CodeRiskLevel.LOW, ()),
    )


def _analysis(source_index):
    execution = PythonExecutionResult(
        ExecutionStatus.COMPLETED, True, "FLAG{execution}", "", 0, False,
        0.1, None, "done", False, True,
    )
    return ExecutionAnalysisResult(execution, (), "FLAG{execution}", True, source_index)


def test_competition_flow_renders_events_results_actions_tools_and_budget(
    monkeypatch, tmp_path
):
    analysis_calls = []
    action_calls = []
    shell, buffer = _shell(
        monkeypatch,
        on_analysis_requested=analysis_calls.append,
        on_action_decision=action_calls.append,
    )
    attachment = tmp_path / "sample.txt"
    attachment.write_text("fixture", encoding="utf-8")
    shell.input_view.question_text.content = "問題"
    shell.input_view.state = shell.input_view.presenter.add_files(
        shell.input_view.state, (attachment.resolve(),)
    )
    shell.input_view._sync_file_list()
    shell.input_view.prepare_analysis()
    assert len(analysis_calls) == 1
    assert analysis_calls[0].question == "問題"
    assert analysis_calls[0].file_paths == (attachment.resolve(),)

    now = datetime(2026, 8, 2, tzinfo=timezone.utc)
    for event_type in (
        AnalysisEventType.ANALYSIS_STARTED,
        AnalysisEventType.AGENT_PLAN_CREATED,
        AnalysisEventType.AGENT_STARTED,
        AnalysisEventType.AGENT_COMPLETED,
        AnalysisEventType.ANALYSIS_COMPLETED,
    ):
        shell.event_subscriber(AnalysisEvent(event_type, "secret event", "phase", now, {}))
    assert len(buffer) == 5
    assert shell.progress_view.history == ()
    shell._event_bridge.drain_once()
    assert shell.state.progress.status.value == "completed"
    assert len(shell.progress_view.history) == 1

    state = _state(shell)
    shell.render(state)
    assert shell.result_panel.result_view.flag_candidate_label.values["text"] == "Flag候補：FLAG{candidate}"
    assert shell.result_panel.agent_view.evidence_list.items == ["evidence"]
    assert shell.action_approval_view.action_list.items
    shell.action_approval_view.action_list.selection = (0,)
    shell.action_approval_view._on_select()
    shell.action_approval_view.approve_button.invoke()
    assert len(action_calls) == 1 and action_calls[0].action_id == "action-1"
    assert shell.external_tool_view.history_list.items == ["strings / completed / sample.bin"]
    assert shell.budget_view.ai_label.values["text"] == "AI：1/5"


def test_code_callbacks_execution_display_and_source_index_safety(monkeypatch):
    decisions = []
    executions = []
    shell, _buffer = _shell(
        monkeypatch,
        on_code_decision=decisions.append,
        on_code_execution_requested=executions.append,
    )
    shell.render_generated_code(GeneratedCodeResult((_code(0), _code(1))))
    shell.code_execution_view.candidate_list.selection = (1,)
    shell.code_execution_view._on_select()
    shell.code_execution_view.approve_button.invoke()
    assert len(decisions) == 1 and decisions[0].source_index == 1

    shell.render_generated_code(
        GeneratedCodeResult((_code(0), _code(1, GeneratedCodeStatus.APPROVED)))
    )
    shell.code_execution_view.candidate_list.selection = (1,)
    shell.code_execution_view._on_select()
    shell.code_execution_view.execute_button.invoke()
    assert len(executions) == 1 and executions[0].source_index == 1
    shell.render_execution_results((_analysis(1),))
    assert shell.code_execution_view.execution_result_list.items == ["[1] completed"]
    assert "[0]" not in shell.code_execution_view.execution_result_list.items[0]

    shell.render_execution_results((_analysis(99),))
    assert "見つかりません" in shell.code_execution_view.execution_warning_label.values["text"]
    legacy = replace(_analysis(1), source_index=None)
    shell.render_execution_results((legacy,))
    assert shell.code_execution_view.execution_result_list.items == ["[0] completed"]


def test_new_empty_state_and_clear_remove_all_previous_display(monkeypatch):
    calls = []
    shell, _buffer = _shell(
        monkeypatch,
        on_analysis_requested=calls.append,
        on_action_decision=calls.append,
        on_code_decision=calls.append,
        on_code_execution_requested=calls.append,
    )
    shell.render(_state(shell))
    shell.render_generated_code(GeneratedCodeResult((_code(0),)))
    shell.render_execution_results((_analysis(0),))
    empty = ApplicationPresenter().initial_state()
    shell.render(empty)
    shell.render_generated_code(None)
    assert shell.result_panel.result_view.answer_text.content == ""
    assert shell.result_panel.agent_view.evidence_list.items == []
    assert shell.action_approval_view.action_list.items == []
    assert shell.external_tool_view.history_list.items == []
    assert shell.budget_view.ai_label.values["text"] == "AI：未設定"
    assert shell.code_execution_view.code_text.content == ""
    assert shell.code_execution_view.execution_result_list.items == []
    shell.input_view.question_text.content = "old"
    shell.progress_view._history.append("old")
    shell.clear()
    assert calls == []
    assert shell.input_view.question_text.content == ""
    assert shell.progress_view.history == ()


def test_shell_does_not_add_secrets_or_run_domain_operations(monkeypatch):
    shell, _buffer = _shell(monkeypatch)
    state = _state(shell)
    shell.render(state)
    rendered = repr(vars(shell.result_panel.result_view)) + repr(vars(shell.external_tool_view))
    for secret in (
        "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN",
        "C:\\private\\secret.bin", "FULL TOOL STDOUT", "FULL TOOL STDERR",
        "prompt secret", "action metadata",
    ):
        assert secret not in rendered
    source = inspect.getsource(
        importlib.import_module("app.gui.application_shell").ProjectAegisApplicationShell
    ).casefold()
    for forbidden in (
        "controller", "challengeservice", "statemanager", "coordinator",
        "runner", "subprocess", "thread", "asyncio", "exec(", "eval(",
        "approve(", "submit",
    ):
        assert forbidden not in source


def test_application_controller_connects_shell_service_and_event_pipeline(monkeypatch):
    publisher = EventPublisher()
    service_calls = []

    class PublishingService:
        def solve(self, question, file_paths):
            service_calls.append((question, file_paths))
            assert shell.analysis_active
            assert shell.input_view.prepare_button.values["state"] == "disabled"
            try:
                shell.clear()
            except RuntimeError:
                pass
            else:
                raise AssertionError("解析中にclearできました。")
            now = datetime(2026, 8, 2, tzinfo=timezone.utc)
            publisher.publish(
                AnalysisEvent(
                    AnalysisEventType.ANALYSIS_STARTED,
                    "started",
                    "analysis",
                    now,
                    {},
                )
            )
            publisher.publish(
                AnalysisEvent(
                    AnalysisEventType.ANALYSIS_COMPLETED,
                    "completed",
                    "completed",
                    now,
                    {},
                )
            )
            return JudgeResult("Misc", "answer")

    controller = ApplicationController(PublishingService(), publisher)
    shell, buffer = _shell(
        monkeypatch,
        on_analysis_requested=controller.handle_analysis_request,
        on_action_decision=controller.handle_action_decision,
        on_code_decision=controller.handle_code_decision,
        on_code_execution_requested=controller.handle_code_execution_request,
    )
    controller.connect_shell(shell)
    shell.input_view.question_text.content = "question"
    shell.input_view.prepare_analysis()
    controller.worker.join(2)
    assert service_calls == [("question", [])]
    assert len(buffer) == 2
    shell._event_bridge.drain_once()
    assert not shell.analysis_active
    assert shell.input_view.prepare_button.values["state"] == "normal"
    assert shell.state.progress.status.value == "completed"
