import tkinter as tk
from collections.abc import Callable

from app.events.analysis_event import AnalysisEventType
from app.judge.judge_result import JudgeResult
from app.presentation.application_presenter import ApplicationPresenter
from app.presentation.event_buffer import AnalysisEventBuffer
from app.presentation.view_models import ApplicationState


class TkEventBridge:
    def __init__(
        self,
        root: tk.Misc,
        buffer: AnalysisEventBuffer,
        presenter: ApplicationPresenter,
        initial_state: ApplicationState,
        on_state_changed: Callable[[ApplicationState], None],
        poll_interval_ms: int = 100,
    ) -> None:
        if (
            not isinstance(poll_interval_ms, int)
            or isinstance(poll_interval_ms, bool)
            or not 10 <= poll_interval_ms <= 5_000
        ):
            raise ValueError(
                "poll_interval_msは10から5000の整数で指定してください。"
            )

        self._root = root
        self._buffer = buffer
        self._presenter = presenter
        self._state = initial_state
        self._on_state_changed = on_state_changed
        self._poll_interval_ms = poll_interval_ms
        self._result_provider: Callable[[], JudgeResult | None] | None = None
        self._running = False
        self._after_id = None

    @property
    def state(self) -> ApplicationState:
        return self._state

    def set_state(self, state: ApplicationState) -> None:
        self._state = state

    def set_result_provider(
        self,
        provider: Callable[[], JudgeResult | None] | None,
    ) -> None:
        if provider is not None and not callable(provider):
            raise TypeError(
                "result providerはCallableまたはNoneで指定してください。"
            )

        self._result_provider = provider

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._schedule()

    def stop(self) -> None:
        self._running = False
        after_id = self._after_id
        self._after_id = None

        if after_id is not None and hasattr(self._root, "after_cancel"):
            try:
                self._root.after_cancel(after_id)
            except Exception:  # noqa: BLE001 - Tk終了中のcancel失敗は停止状態を維持
                return

    def drain_once(self) -> ApplicationState:
        events = self._buffer.drain()

        if not events:
            return self._state

        state = self._state

        for event in events:
            state = self._presenter.apply_event(state, event)

            if event.event_type is AnalysisEventType.ANALYSIS_COMPLETED:
                state = self._present_completed_result(state)

        self._state = state
        self._on_state_changed(state)

        return state

    def _present_completed_result(
        self,
        state: ApplicationState,
    ) -> ApplicationState:
        if self._result_provider is None:
            return state

        result = self._result_provider()

        if result is None:
            return state

        return self._presenter.present_result(state, result)

    def _poll(self) -> None:
        self._after_id = None

        if not self._running:
            return

        try:
            self.drain_once()
        except Exception:
            self._running = False
            raise

        if self._running:
            self._schedule()

    def _schedule(self) -> None:
        self._after_id = self._root.after(
            self._poll_interval_ms,
            self._poll,
        )