import inspect
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from app.events.analysis_event import AnalysisEvent, AnalysisEventType
from app.events.event_publisher import EventPublisher

FIXED_TIME = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def _event(metadata: dict[str, object] | None = None) -> AnalysisEvent:
    return AnalysisEvent(
        event_type=AnalysisEventType.ANALYSIS_STARTED,
        message="解析を開始しました。",
        phase="input",
        timestamp=FIXED_TIME,
        metadata=metadata or {},
    )


def test_creates_analysis_event_with_typed_fields():
    event = _event({"file_count": 2})

    assert event.event_type is AnalysisEventType.ANALYSIS_STARTED
    assert event.message == "解析を開始しました。"
    assert event.phase == "input"
    assert event.timestamp == FIXED_TIME
    assert event.metadata == {"file_count": 2}


def test_defines_all_required_event_types():
    assert {event_type.value for event_type in AnalysisEventType} == {
        "analysis_started",
        "file_analysis_started",
        "file_analysis_completed",
        "local_solution_found",
        "agent_plan_created",
        "agent_started",
        "agent_completed",
        "agent_failed",
        "agent_aggregation_completed",
        "ai_analysis_started",
        "ai_analysis_completed",
        "analysis_completed",
        "analysis_failed",
    }


def test_metadata_is_copied_from_caller():
    metadata = {"file_name": "before.zip"}
    event = _event(metadata)

    metadata["file_name"] = "after.zip"

    assert event.metadata["file_name"] == "before.zip"


def test_metadata_is_read_only():
    event = _event({"file_count": 1})

    with pytest.raises(TypeError):
        event.metadata["file_count"] = 2  # type: ignore[index]


def test_event_fields_cannot_be_reassigned():
    event = _event()

    with pytest.raises(FrozenInstanceError):
        event.phase = "completed"  # type: ignore[misc]


def test_subscribe_and_publish_deliver_same_event():
    publisher = EventPublisher()
    received: list[AnalysisEvent] = []
    publisher.subscribe(received.append)
    event = _event()

    failures = publisher.publish(event)

    assert received == [event]
    assert failures == ()


def test_multiple_subscribers_are_called_in_registration_order():
    publisher = EventPublisher()
    calls: list[str] = []
    publisher.subscribe(lambda event: calls.append("first"))
    publisher.subscribe(lambda event: calls.append("second"))

    publisher.publish(_event())

    assert calls == ["first", "second"]


def test_duplicate_subscriber_is_registered_once():
    publisher = EventPublisher()
    received: list[AnalysisEvent] = []
    publisher.subscribe(received.append)
    publisher.subscribe(received.append)

    publisher.publish(_event())

    assert len(received) == 1


def test_unsubscribe_stops_future_notifications():
    publisher = EventPublisher()
    received: list[AnalysisEvent] = []
    publisher.subscribe(received.append)
    publisher.unsubscribe(received.append)

    publisher.publish(_event())

    assert received == []


def test_unsubscribe_unknown_subscriber_is_safe():
    publisher = EventPublisher()

    publisher.unsubscribe(lambda event: None)

    assert publisher.publish(_event()) == ()


def test_publish_without_subscribers_is_safe():
    assert EventPublisher().publish(_event()) == ()


def test_subscriber_failure_is_returned_without_stopping_others():
    publisher = EventPublisher()
    received: list[AnalysisEvent] = []

    def failing_subscriber(event: AnalysisEvent) -> None:
        raise ValueError("表示に失敗")

    publisher.subscribe(failing_subscriber)
    publisher.subscribe(received.append)

    failures = publisher.publish(_event())

    assert len(received) == 1
    assert len(failures) == 1
    assert failures[0].subscriber_name.endswith("failing_subscriber")
    assert failures[0].error_type == "ValueError"
    assert failures[0].message == "表示に失敗"


def test_unsubscribe_during_publish_uses_stable_snapshot():
    publisher = EventPublisher()
    calls: list[str] = []

    def second(event: AnalysisEvent) -> None:
        calls.append("second")

    def first(event: AnalysisEvent) -> None:
        calls.append("first")
        publisher.unsubscribe(second)

    publisher.subscribe(first)
    publisher.subscribe(second)

    publisher.publish(_event())
    publisher.publish(_event())

    assert calls == ["first", "second", "first"]


def test_subscribe_during_publish_applies_from_next_publish():
    publisher = EventPublisher()
    calls: list[str] = []

    def later(event: AnalysisEvent) -> None:
        calls.append("later")

    def first(event: AnalysisEvent) -> None:
        calls.append("first")
        publisher.subscribe(later)

    publisher.subscribe(first)

    publisher.publish(_event())
    assert calls == ["first"]

    publisher.publish(_event())
    assert calls == ["first", "first", "later"]


def test_same_event_can_be_published_multiple_times():
    publisher = EventPublisher()
    received: list[AnalysisEvent] = []
    publisher.subscribe(received.append)
    event = _event()

    publisher.publish(event)
    publisher.publish(event)

    assert received == [event, event]


def test_publisher_does_not_add_sensitive_metadata():
    publisher = EventPublisher()
    event = _event({"file_name": "challenge.zip"})
    publisher.publish(event)

    assert dict(event.metadata) == {"file_name": "challenge.zip"}
    assert "api_key" not in event.metadata
    assert "prompt" not in event.metadata


def test_event_modules_are_independent_of_ui_and_async_implementations():
    import app.events.analysis_event as event_module
    import app.events.event_publisher as publisher_module

    source = inspect.getsource(event_module) + inspect.getsource(publisher_module)

    assert "app.main" not in source
    assert "GUI" not in source
    assert "asyncio" not in source
    assert "Thread" not in source
    assert "Queue" not in source
    assert "Singleton" not in source
