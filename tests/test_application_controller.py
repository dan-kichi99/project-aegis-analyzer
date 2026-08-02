import inspect
from dataclasses import dataclass

import pytest

from app.application import ApplicationController
from app.events.analysis_event import AnalysisEvent, AnalysisEventType
from app.events.event_publisher import EventPublisher
from app.judge.judge_result import JudgeResult
from app.presentation import (
    ActionApprovalDecision,
    ActionApprovalRequest,
    AnalysisEventBuffer,
    AnalysisRequest,
    CodeApprovalDecision,
    CodeApprovalRequest,
    CodeExecutionRequest,
    GuiEventSubscriber,
)


class FakeService:
    def __init__(self, publisher=None, error=None, during_call=None):
        self.publisher = publisher
        self.error = error
        self.during_call = during_call
        self.calls = []

    def solve(self, question, file_paths):
        self.calls.append((question, file_paths))
        if self.during_call is not None:
            self.during_call()
        if self.publisher is not None:
            self.publisher.publish(_event(AnalysisEventType.ANALYSIS_STARTED))
        if self.error is not None:
            raise self.error
        if self.publisher is not None:
            self.publisher.publish(_event(AnalysisEventType.ANALYSIS_COMPLETED))
        return JudgeResult("Misc", "answer")


@dataclass
class FakeShell:
    event_subscriber: object

    def __post_init__(self):
        self.active_values = []

    def set_analysis_active(self, active):
        self.active_values.append(active)


def _event(event_type):
    from datetime import datetime, timezone

    return AnalysisEvent(event_type, "fixed", "phase", datetime.now(timezone.utc), {})


def test_analysis_request_reaches_service_once_and_input_is_locked_during_call(tmp_path):
    publisher = EventPublisher()
    buffer = AnalysisEventBuffer()
    shell = FakeShell(GuiEventSubscriber(buffer))
    holder = {}
    service = FakeService(during_call=lambda: holder.update(active=shell.active_values[-1]))
    controller = ApplicationController(service, publisher)
    controller.connect_shell(shell)
    paths = tuple((tmp_path / name).resolve() for name in ("one.txt", "two.txt"))
    for path in paths:
        path.write_text("fixture", encoding="utf-8")
    request = AnalysisRequest("question", paths)
    worker = controller.handle_analysis_request(request)
    worker.join(2)
    assert service.calls == [("question", list(paths))]
    assert holder["active"] is True
    assert shell.active_values == [True]
    assert controller.analysis_active is False
    assert controller.last_result.answer == "answer"
    assert request.question == "question" and request.file_paths == paths


def test_events_flow_to_connected_gui_subscriber_without_direct_state_update():
    publisher = EventPublisher()
    buffer = AnalysisEventBuffer()
    shell = FakeShell(GuiEventSubscriber(buffer))
    controller = ApplicationController(FakeService(publisher), publisher)
    controller.connect_shell(shell)
    worker = controller.handle_analysis_request(AnalysisRequest("question", ()))
    worker.join(2)
    assert [event.event_type for event in buffer.drain()] == [
        AnalysisEventType.ANALYSIS_STARTED,
        AnalysisEventType.ANALYSIS_COMPLETED,
    ]


def test_failure_event_is_published_input_is_restored_and_error_propagates():
    publisher = EventPublisher()
    buffer = AnalysisEventBuffer()
    shell = FakeShell(GuiEventSubscriber(buffer))
    error = RuntimeError("failure")
    controller = ApplicationController(FakeService(error=error), publisher)
    controller.connect_shell(shell)
    worker = controller.handle_analysis_request(AnalysisRequest("question", ()))
    worker.join(2)
    event = buffer.drain()[0]
    assert event.event_type is AnalysisEventType.ANALYSIS_FAILED
    assert event.metadata == {"error_type": "RuntimeError"}
    assert shell.active_values == [True]
    assert not controller.analysis_active


def test_reentrant_analysis_is_rejected_without_second_service_call():
    publisher = EventPublisher()
    controller = None

    def reenter():
        with pytest.raises(RuntimeError, match="実行中"):
            controller.handle_analysis_request(AnalysisRequest("second", ()))

    service = FakeService(during_call=reenter)
    controller = ApplicationController(service, publisher)
    worker = controller.handle_analysis_request(AnalysisRequest("first", ()))
    worker.join(2)
    assert len(service.calls) == 1


def test_action_and_code_requests_are_forwarded_by_identity_once():
    action_calls = []
    code_calls = []
    execution_calls = []
    controller = ApplicationController(
        FakeService(),
        EventPublisher(),
        on_action_decision=action_calls.append,
        on_code_decision=code_calls.append,
        on_code_execution_requested=execution_calls.append,
    )
    action = ActionApprovalRequest("action", ActionApprovalDecision.DEFER)
    code = CodeApprovalRequest(2, CodeApprovalDecision.REJECT)
    execution = CodeExecutionRequest(2)
    controller.handle_action_decision(action)
    controller.handle_code_decision(code)
    controller.handle_code_execution_request(execution)
    assert action_calls == [action] and action_calls[0] is action
    assert code_calls == [code] and code_calls[0] is code
    assert execution_calls == [execution] and execution_calls[0] is execution


def test_connect_is_idempotent_and_disconnect_stops_event_forwarding():
    publisher = EventPublisher()
    buffer = AnalysisEventBuffer()
    shell = FakeShell(GuiEventSubscriber(buffer))
    controller = ApplicationController(FakeService(), publisher)
    controller.connect_shell(shell)
    controller.connect_shell(shell)
    publisher.publish(_event(AnalysisEventType.ANALYSIS_STARTED))
    assert len(buffer) == 1
    controller.disconnect_shell()
    publisher.publish(_event(AnalysisEventType.ANALYSIS_COMPLETED))
    assert len(buffer) == 1


def test_cancel_keeps_worker_active_until_exit_and_discards_result():
    import threading

    entered = threading.Event()
    release = threading.Event()

    class BlockingService:
        def solve(self, _question, _file_paths):
            entered.set()
            release.wait(2)
            return JudgeResult("Misc", "must not be reflected")

    publisher = EventPublisher()
    buffer = AnalysisEventBuffer()
    shell = FakeShell(GuiEventSubscriber(buffer))
    controller = ApplicationController(BlockingService(), publisher)
    controller.connect_shell(shell)
    worker = controller.handle_analysis_request(AnalysisRequest("question", ()))
    assert entered.wait(1)
    assert controller.cancel_analysis()
    assert controller.analysis_active and worker.is_alive()
    with pytest.raises(RuntimeError, match="実行中"):
        controller.handle_analysis_request(AnalysisRequest("again", ()))
    release.set()
    worker.join(2)
    assert not controller.analysis_active
    assert controller.last_result is None and worker.result is None
    event = buffer.drain()[0]
    assert event.event_type is AnalysisEventType.ANALYSIS_CANCELLED
    assert controller.cancel_analysis() is False


def test_application_controller_has_no_state_render_thread_or_process_logic():
    source = inspect.getsource(ApplicationController).casefold()
    for forbidden in (
        ".render(", "applicationstate", "dataclasses.replace",
        "asyncio", "subprocess", "threadpoolexecutor", "pythonexecutionrunner", "coordinator",
        "statemanager", "mainloop", "sleep(",
    ):
        assert forbidden not in source
