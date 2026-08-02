import importlib
import sys

from app.application.startup_result import StartupMode, StartupResult, StartupStatus


class FakeRoot:
    def __init__(self):
        self.titles = []
        self.mainloop_calls = 0
        self.destroy_calls = 0

    def title(self, value):
        self.titles.append(value)

    def mainloop(self):
        self.mainloop_calls += 1

    def destroy(self):
        self.destroy_calls += 1


class FakeFrame:
    def __init__(self):
        self.pack_calls = 0

    def pack(self, **_kwargs):
        self.pack_calls += 1


class FakeShell:
    def __init__(self):
        self.frame = FakeFrame()
        self.starts = 0
        self.stops = 0

    def start_event_bridge(self):
        self.starts += 1

    def stop_event_bridge(self):
        self.stops += 1


class FakeController:
    def __init__(self):
        self.disconnects = 0

    def disconnect_shell(self):
        self.disconnects += 1


def _startup(status, exit_code=0):
    return StartupResult(StartupMode.GUI, status, "固定起動メッセージ", None, exit_code)


def test_import_does_not_create_tk_or_start_mainloop(monkeypatch):
    import tkinter

    calls = []
    monkeypatch.setattr(tkinter, "Tk", lambda: calls.append("Tk"))
    sys.modules.pop("app.gui_main", None)
    importlib.import_module("app.gui_main")
    assert calls == []


def test_main_builds_gui_starts_bridge_and_cleans_up(monkeypatch):
    module = importlib.import_module("app.gui_main")
    root = FakeRoot()
    shell = FakeShell()
    controller = FakeController()
    monkeypatch.setattr(module, "_create_root", lambda: root)
    monkeypatch.setattr(module.StartupService, "check", lambda _self, _mode: _startup(StartupStatus.READY))
    monkeypatch.setattr(module, "_build_application", lambda _root: (shell, controller))
    assert module.main() == 0
    assert root.mainloop_calls == 1
    assert shell.starts == shell.stops == 1
    assert controller.disconnects == 1
    assert root.destroy_calls == 1
    assert shell.frame.pack_calls == 1


def test_blocked_startup_does_not_create_root(monkeypatch, capsys):
    module = importlib.import_module("app.gui_main")
    roots = []
    monkeypatch.setattr(module, "_create_root", lambda: roots.append(FakeRoot()))
    monkeypatch.setattr(module.StartupService, "check", lambda _self, _mode: _startup(StartupStatus.BLOCKED, 2))
    assert module.main() == 2
    assert roots == []
    assert "固定起動メッセージ" in capsys.readouterr().err


def test_gui_failure_hides_exception_details_and_returns_one(monkeypatch, capsys):
    module = importlib.import_module("app.gui_main")
    root = FakeRoot()
    monkeypatch.setattr(module, "_create_root", lambda: root)
    monkeypatch.setattr(module.StartupService, "check", lambda _self, _mode: _startup(StartupStatus.READY))
    monkeypatch.setattr(
        module,
        "_build_application",
        lambda _root: (_ for _ in ()).throw(RuntimeError("OPENAI_API_KEY_TEST_SECRET")),
    )
    assert module.main() == 1
    output = capsys.readouterr().err
    assert "OPENAI_API_KEY_TEST_SECRET" not in output
    assert root.destroy_calls == 1
