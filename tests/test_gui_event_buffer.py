import inspect
from datetime import datetime, timezone

import pytest

from app.events.analysis_event import AnalysisEvent, AnalysisEventType
from app.gui.event_bridge import TkEventBridge
from app.presentation import (
    AnalysisEventBuffer,
    ApplicationPresenter,
    ApplicationStatus,
    GuiEventSubscriber,
)

NOW = datetime(2026, 8, 2, tzinfo=timezone.utc)


def _event(event_type=AnalysisEventType.ANALYSIS_STARTED, phase="phase"):
    return AnalysisEvent(event_type, "FLAG{secret} prompt", phase, NOW, {"flag": "hidden"})


class FakeRoot:
    def __init__(self, cancel_error=False):
        self.scheduled = []
        self.cancelled = []
        self.cancel_error = cancel_error

    def after(self, interval, callback):
        identifier = f"after-{len(self.scheduled)}"
        self.scheduled.append((identifier, interval, callback))
        return identifier

    def after_cancel(self, identifier):
        self.cancelled.append(identifier)
        if self.cancel_error:
            raise RuntimeError("window closed")


class RecordingPresenter(ApplicationPresenter):
    def __init__(self):
        self.events = []

    def apply_event(self, state, event):
        self.events.append(event)
        return super().apply_event(state, event)


def test_buffer_push_drain_order_limit_clear_and_event_immutability():
    buffer = AnalysisEventBuffer()
    events = tuple(_event(phase=str(index)) for index in range(4))
    for event in events:
        buffer.push(event)
    assert len(buffer) == 4
    assert buffer.drain(2) == events[:2]
    assert buffer.drain(100) == events[2:]
    assert events[0].metadata == {"flag": "hidden"}
    buffer.push(events[0])
    buffer.clear()
    assert len(buffer) == 0 and buffer.drain() == ()


@pytest.mark.parametrize("value", [0, 1001, True])
def test_buffer_rejects_invalid_max_items(value):
    with pytest.raises(ValueError, match="max_items"):
        AnalysisEventBuffer().drain(value)


def test_subscriber_only_pushes_to_its_buffer():
    buffer = AnalysisEventBuffer()
    subscriber = GuiEventSubscriber(buffer)
    event = _event()
    subscriber(event)
    assert buffer.drain() == (event,)
    source = inspect.getsource(GuiEventSubscriber)
    for forbidden in ("tkinter", "presenter", "print(", "logging", "open("):
        assert forbidden not in source


@pytest.mark.parametrize("interval", [10, 5_000])
def test_bridge_start_is_idempotent_stop_cancels_and_restart_works(interval):
    root = FakeRoot()
    bridge = TkEventBridge(
        root,
        AnalysisEventBuffer(),
        ApplicationPresenter(),
        ApplicationPresenter().initial_state(),
        lambda _state: None,
        interval,
    )
    assert root.scheduled == []
    bridge.start()
    bridge.start()
    assert len(root.scheduled) == 1 and root.scheduled[0][1] == interval
    bridge.stop()
    assert root.cancelled == ["after-0"]
    bridge.start()
    assert len(root.scheduled) == 2


@pytest.mark.parametrize("interval", [9, 5_001, True])
def test_bridge_rejects_invalid_interval(interval):
    with pytest.raises(ValueError, match="poll_interval"):
        TkEventBridge(
            FakeRoot(),
            AnalysisEventBuffer(),
            ApplicationPresenter(),
            ApplicationPresenter().initial_state(),
            lambda _state: None,
            interval,
        )


def test_drain_applies_events_in_order_and_calls_back_once():
    buffer = AnalysisEventBuffer()
    events = (
        _event(AnalysisEventType.ANALYSIS_STARTED),
        _event(AnalysisEventType.AGENT_STARTED),
        _event(AnalysisEventType.ANALYSIS_COMPLETED),
    )
    for event in events:
        buffer.push(event)
    presenter = RecordingPresenter()
    initial = presenter.initial_state()
    states = []
    bridge = TkEventBridge(FakeRoot(), buffer, presenter, initial, states.append)
    result = bridge.drain_once()
    assert presenter.events == list(events)
    assert len(states) == 1 and states[0] is result
    assert result.progress.status is ApplicationStatus.COMPLETED
    assert initial.progress.status is ApplicationStatus.IDLE
    assert bridge.drain_once() is result and len(states) == 1


def test_stop_preserves_events_and_cancel_failure_is_safe():
    buffer = AnalysisEventBuffer()
    buffer.push(_event())
    root = FakeRoot(cancel_error=True)
    bridge = TkEventBridge(
        root,
        buffer,
        ApplicationPresenter(),
        ApplicationPresenter().initial_state(),
        lambda _state: None,
    )
    bridge.start()
    bridge.stop()
    assert len(buffer) == 1


def test_callback_exception_propagates_and_poll_is_not_rescheduled():
    buffer = AnalysisEventBuffer()
    buffer.push(_event())
    root = FakeRoot()

    def fail(_state):
        raise RuntimeError("render failed")

    bridge = TkEventBridge(
        root,
        buffer,
        ApplicationPresenter(),
        ApplicationPresenter().initial_state(),
        fail,
    )
    bridge.start()
    callback = root.scheduled[0][2]
    with pytest.raises(RuntimeError, match="render failed"):
        callback()
    assert len(root.scheduled) == 1


def test_bridge_and_buffer_create_no_threads_or_execution_dependencies():
    source = inspect.getsource(TkEventBridge) + inspect.getsource(AnalysisEventBuffer)
    for forbidden in (
        "Thread(",
        "asyncio",
        "sleep(",
        "subprocess",
        "Controller",
        "ChallengeService",
        "OpenAI",
    ):
        assert forbidden not in source
