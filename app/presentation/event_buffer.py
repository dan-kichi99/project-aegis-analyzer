from queue import Empty, Queue

from app.events.analysis_event import AnalysisEvent


class AnalysisEventBuffer:
    def __init__(self) -> None:
        self._queue: Queue[AnalysisEvent] = Queue()

    def push(self, event: AnalysisEvent) -> None:
        self._queue.put(event)

    def drain(self, max_items: int = 100) -> tuple[AnalysisEvent, ...]:
        if (
            not isinstance(max_items, int)
            or isinstance(max_items, bool)
            or not 1 <= max_items <= 1_000
        ):
            raise ValueError("max_itemsは1から1000の整数で指定してください。")
        events: list[AnalysisEvent] = []
        for _ in range(max_items):
            try:
                events.append(self._queue.get_nowait())
            except Empty:
                break
        return tuple(events)

    def clear(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except Empty:
                return

    def __len__(self) -> int:
        return self._queue.qsize()


class GuiEventSubscriber:
    def __init__(self, buffer: AnalysisEventBuffer) -> None:
        self._buffer = buffer

    def __call__(self, event: AnalysisEvent) -> None:
        self._buffer.push(event)
