import threading
from collections.abc import Callable
from pathlib import Path

from app.judge.judge_result import JudgeResult

SolveCallable = Callable[[str, list[str | Path] | None], JudgeResult]
CompletionCallback = Callable[["AnalysisWorker"], None]


class AnalysisWorker:
    def __init__(
        self,
        solve: SolveCallable,
        question: str,
        file_paths: tuple[Path, ...],
        on_completed: CompletionCallback | None = None,
    ) -> None:
        self._solve = solve
        self._question = question
        self._file_paths = file_paths
        self._on_completed = on_completed
        self._cancel_requested = threading.Event()
        self._completed = threading.Event()
        self._result: JudgeResult | None = None
        self._error: Exception | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="project-aegis-analysis",
            daemon=True,
        )

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested.is_set()

    @property
    def completed(self) -> bool:
        return self._completed.is_set()

    @property
    def result(self) -> JudgeResult | None:
        return self._result

    @property
    def error(self) -> Exception | None:
        return self._error

    def start(self) -> None:
        self._thread.start()

    def cancel(self) -> None:
        self._cancel_requested.set()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    def _run(self) -> None:
        try:
            result = self._solve(self._question, list(self._file_paths))
            if not self.cancel_requested:
                self._result = result
        except Exception as error:  # noqa: BLE001 - Worker境界でControllerへ保持
            self._error = error
        finally:
            self._completed.set()
            if self._on_completed is not None:
                self._on_completed(self)
