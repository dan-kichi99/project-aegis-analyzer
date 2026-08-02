import importlib
import inspect
from unittest.mock import patch

from app.presentation import AnalysisInputPresenter, AnalysisRequest


class FakeWidget:
    def __init__(self, _parent=None, **values):
        self.values = values
        self.items = []
        self.selection = ()
        self.content = ""

    def pack(self, **_values):
        return None

    def configure(self, **values):
        self.values.update(values)

    def get(self, *_values):
        return self.content

    def delete(self, *_values):
        self.items.clear()
        self.content = ""

    def insert(self, _position, value):
        self.items.append(value)

    def curselection(self):
        return self.selection


def _view(monkeypatch, callback=None):
    module = importlib.import_module("app.gui.input_view")
    for name in ("Frame", "Label", "Text", "Listbox", "Button"):
        monkeypatch.setattr(module.tk, name, FakeWidget)
    return module, module.AnalysisInputView(object(), AnalysisInputPresenter(), callback)


def test_import_does_not_create_tk_or_start_mainloop():
    module = importlib.import_module("app.gui.input_view")
    source = inspect.getsource(module)
    assert "tk.Tk(" not in source
    assert "mainloop(" not in source


def test_dialog_cancel_keeps_state(monkeypatch):
    module, view = _view(monkeypatch)
    monkeypatch.setattr(module.filedialog, "askopenfilenames", lambda **_values: ())
    original = view.state
    view.add_files()
    assert view.state is original


def test_file_add_list_names_remove_and_clear(monkeypatch, tmp_path):
    module, view = _view(monkeypatch)
    paths = []
    for name in ("one.txt", "two.txt"):
        path = (tmp_path / name).resolve()
        path.write_text("fixture", encoding="utf-8")
        paths.append(path)
    monkeypatch.setattr(
        module.filedialog,
        "askopenfilenames",
        lambda **_values: tuple(map(str, paths)),
    )
    view.add_files()
    assert view.file_list.items == ["one.txt", "two.txt"]
    assert all(str(tmp_path) not in item for item in view.file_list.items)
    view.file_list.selection = (0,)
    view.remove_selected()
    assert view.file_list.items == ["two.txt"]
    view.clear_files()
    assert view.file_list.items == []


def test_question_validation_error_and_valid_callback(monkeypatch):
    calls = []
    _module, view = _view(monkeypatch, calls.append)
    view.question_text.content = "  "
    view.prepare_analysis()
    assert calls == []
    assert "問題文または添付ファイル" in view.error_label.values["text"]
    view.question_text.content = "line one\nline two"
    view.prepare_analysis()
    assert len(calls) == 1
    assert isinstance(calls[0], AnalysisRequest)
    assert calls[0].question == "line one\nline two"
    assert view.error_label.values["text"] == ""


def test_callback_exception_propagates(monkeypatch):
    def fail(_request):
        raise RuntimeError("callback failure")

    _module, view = _view(monkeypatch, fail)
    view.question_text.content = "question"
    with patch.object(view.presenter, "validate", wraps=view.presenter.validate):
        try:
            view.prepare_analysis()
        except RuntimeError as error:
            assert str(error) == "callback failure"
        else:
            raise AssertionError("callback例外が伝播していません。")


def test_view_has_no_analysis_execution_dependencies():
    module = importlib.import_module("app.gui.input_view")
    source = inspect.getsource(module.AnalysisInputView)
    for forbidden in (
        "ChallengeService",
        "Controller",
        "FileLoader",
        "subprocess",
        "thread",
        "asyncio",
        "OpenAI",
        "mainloop",
    ):
        assert forbidden not in source


def test_set_enabled_and_clear_reset_all_input_widgets(monkeypatch):
    _module, view = _view(monkeypatch)
    view.question_text.content = "old question"
    view.error_label.configure(text="old error")
    view.set_enabled(False)
    for widget in (
        view.question_text,
        view.file_list,
        view.add_button,
        view.remove_button,
        view.clear_button,
        view.prepare_button,
    ):
        assert widget.values["state"] == "disabled"
    assert view.cancel_button.values["state"] == "normal"
    view.set_enabled(True)
    assert view.prepare_button.values["state"] == "normal"
    assert view.cancel_button.values["state"] == "disabled"
    view.clear()
    assert view.question_text.content == ""
    assert view.file_list.items == []
    assert view.error_label.values["text"] == ""
