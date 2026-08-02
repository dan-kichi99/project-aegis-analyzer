import inspect
import threading

from app.application import AnalysisWorker
from app.judge.judge_result import JudgeResult


def test_worker_calls_solve_once_and_preserves_result():
    calls = []

    def solve(question, paths):
        calls.append((question, paths, threading.current_thread().name))
        return JudgeResult("Misc", "answer")

    worker = AnalysisWorker(solve, "question", (), None)
    worker.start()
    worker.join(2)
    assert calls == [("question", [], "project-aegis-analysis")]
    assert worker.completed and not worker.is_alive()
    assert worker.result.answer == "answer" and worker.error is None


def test_cancel_flag_does_not_kill_thread_and_suppresses_result():
    release = threading.Event()
    entered = threading.Event()

    def solve(_question, _paths):
        entered.set()
        release.wait(2)
        return JudgeResult("Misc", "cancelled result")

    worker = AnalysisWorker(solve, "question", ())
    worker.start()
    assert entered.wait(1)
    worker.cancel()
    assert worker.cancel_requested and worker.is_alive()
    release.set()
    worker.join(2)
    assert worker.completed and worker.result is None


def test_worker_captures_error_and_notifies_once():
    completions = []

    def fail(_question, _paths):
        raise RuntimeError("failure")

    worker = AnalysisWorker(fail, "question", (), completions.append)
    worker.start()
    worker.join(2)
    assert isinstance(worker.error, RuntimeError)
    assert completions == [worker]


def test_worker_has_no_gui_asyncio_pool_process_or_kill_operations():
    source = inspect.getsource(importlib_module := __import__(
        "app.application.analysis_worker", fromlist=["*"]
    )).casefold()
    assert importlib_module.AnalysisWorker is AnalysisWorker
    for forbidden in (
        "tkinter", "widget", "asyncio", "multiprocessing", "subprocess",
        "threadpoolexecutor", ".kill(", "challengeservice",
    ):
        assert forbidden not in source
