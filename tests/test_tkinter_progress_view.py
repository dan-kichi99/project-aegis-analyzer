import importlib
import inspect

from app.presentation import ApplicationStatus, ProgressViewModel


class FakeWidget:
    def __init__(self, _parent=None, **values):
        self.values = values
        self.items = []
        self.start_calls = 0
        self.stop_calls = 0

    def pack(self, **_values):
        return None

    def configure(self, **values):
        self.values.update(values)

    def start(self):
        self.start_calls += 1

    def stop(self):
        self.stop_calls += 1

    def delete(self, *_values):
        self.items.clear()

    def insert(self, _position, value):
        self.items.append(value)


def _view(monkeypatch):
    module = importlib.import_module("app.gui.progress_view")
    for name in ("Frame", "Label", "Listbox"):
        monkeypatch.setattr(module.tk, name, FakeWidget)
    monkeypatch.setattr(module.ttk, "Progressbar", FakeWidget)
    return module, module.AnalysisProgressView(object())


def _progress(status, percent=None, agent=None, error=None, message="fixed message"):
    return ProgressViewModel(status, "phase", message, percent, agent, error)


def test_render_all_statuses_and_visible_fields(monkeypatch):
    _module, view = _view(monkeypatch)
    for status in ApplicationStatus:
        progress = _progress(status, agent="rev", error="RuntimeError")
        view.render(progress)
        assert view.status_label.values["text"] == status.value
        assert view.phase_label.values["text"] == "phase"
        assert view.message_label.values["text"] == "fixed message"
        assert view.agent_label.values["text"] == "rev"
        assert view.error_label.values["text"] == "RuntimeError"
    assert view.progressbar.values["value"] == 0


def test_determinate_indeterminate_and_completed_progress(monkeypatch):
    _module, view = _view(monkeypatch)
    view.render(_progress(ApplicationStatus.ANALYZING))
    view.render(_progress(ApplicationStatus.ANALYZING))
    assert view.progressbar.values["mode"] == "indeterminate"
    assert view.progressbar.start_calls == 1
    view.render(_progress(ApplicationStatus.ANALYZING, 40))
    assert view.progressbar.stop_calls == 1
    assert view.progressbar.values["mode"] == "determinate"
    assert view.progressbar.values["value"] == 40
    view.render(_progress(ApplicationStatus.COMPLETED))
    assert view.progressbar.values["value"] == 100


def test_history_keeps_latest_hundred_and_clear_removes_all(monkeypatch):
    _module, view = _view(monkeypatch)
    for index in range(101):
        view.append_history(
            ProgressViewModel(
                ApplicationStatus.ANALYZING,
                f"phase-{index}",
                f"message-{index}",
                None,
                None,
                None,
            )
        )
    assert len(view.history) == 100
    assert "phase-0" not in view.history[0]
    assert "phase-1" in view.history[0]
    assert len(view.history_list.items) == 100
    view.clear_history()
    assert view.history == () and view.history_list.items == []


def test_progress_view_only_renders_presenter_values_without_unsafe_dependencies(
    monkeypatch,
):
    module, view = _view(monkeypatch)
    progress = _progress(
        ApplicationStatus.ANALYZING,
        message="安全な固定表示",
    )
    view.render(progress)
    view.append_history(progress)
    rendered = repr(view.message_label.values) + repr(view.history)
    assert "FLAG{secret}" not in rendered
    assert "prompt secret" not in rendered
    source = inspect.getsource(module.AnalysisProgressView)
    for forbidden in (
        "AnalysisEvent",
        "subprocess",
        "thread",
        "asyncio",
        "sleep(",
        "Controller",
        "ChallengeService",
        "mainloop",
    ):
        assert forbidden not in source


def test_module_import_does_not_create_tk_or_start_mainloop():
    module = importlib.import_module("app.gui.progress_view")
    source = inspect.getsource(module)
    assert "tk.Tk(" not in source
    assert "mainloop(" not in source
