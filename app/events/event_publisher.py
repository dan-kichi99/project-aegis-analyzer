from collections.abc import Callable
from dataclasses import dataclass

from app.events.analysis_event import AnalysisEvent

EventSubscriber = Callable[[AnalysisEvent], None]


@dataclass(slots=True, frozen=True)
class SubscriberFailure:
    subscriber_name: str
    error_type: str
    message: str


class EventPublisher:
    """登録順に同期通知し、受信失敗を構造化して返すPublisher。"""

    def __init__(self) -> None:
        self._subscribers: list[EventSubscriber] = []

    def subscribe(self, subscriber: EventSubscriber) -> None:
        if subscriber not in self._subscribers:
            self._subscribers.append(subscriber)

    def unsubscribe(self, subscriber: EventSubscriber) -> None:
        if subscriber in self._subscribers:
            self._subscribers.remove(subscriber)

    def publish(
        self,
        event: AnalysisEvent,
    ) -> tuple[SubscriberFailure, ...]:
        failures: list[SubscriberFailure] = []
        for subscriber in tuple(self._subscribers):
            try:
                subscriber(event)
            except Exception as error:  # noqa: BLE001 - 失敗を構造化して継続
                failures.append(
                    SubscriberFailure(
                        subscriber_name=self._subscriber_name(subscriber),
                        error_type=type(error).__name__,
                        message=str(error),
                    )
                )
        return tuple(failures)

    def _subscriber_name(self, subscriber: EventSubscriber) -> str:
        return getattr(
            subscriber,
            "__qualname__",
            type(subscriber).__qualname__,
        )
