import importlib
import inspect
from dataclasses import replace

from app.presentation import (
    ApplicationPresenter,
    ExternalToolViewModel,
    ToolBudgetPresenter,
)


class FakeWidget:
    def __init__(self, _parent=None, **values):
        self.values = values
        self.items = []

    def pack(self, **_values):
        return None

    def configure(self, **values):
        self.values.update(values)

    def delete(self, *_values):
        self.items.clear()

    def insert(self, _position, value):
        self.items.append(value)


def _view(monkeypatch):
    module = importlib.import_module("app.gui.external_tool_view")
    for name in ("Frame", "Label", "Listbox"):
        monkeypatch.setattr(module.tk, name, FakeWidget)
    return module, module.ExternalToolView(object(), ToolBudgetPresenter())


def _state(*tools):
    return replace(ApplicationPresenter().initial_state(), external_tools=tools)


def test_import_is_safe_without_tk_or_mainloop():
    source = inspect.getsource(importlib.import_module("app.gui.external_tool_view"))
    assert "tk.Tk(" not in source and "mainloop(" not in source


def test_none_and_clear_remove_previous_history(monkeypatch):
    _module, view = _view(monkeypatch)
    tool = ExternalToolViewModel("file", "completed", "x.bin", "summary", 0, (), False, None)
    view.render(_state(tool))
    view.render(None)
    assert view.history_list.items == []
    assert view.tool_type_label.values["text"] == "外部Tool実行履歴はありません。"
    assert view.evidence_list.items == []
    view.render(_state(tool))
    view.clear()
    assert view.history_list.items == []


def test_tool_history_detail_evidence_error_and_repeated_display(monkeypatch):
    _module, view = _view(monkeypatch)
    first = ExternalToolViewModel(
        "strings", "failed", "sample.bin", "summary", 2,
        ("source: first", "source: second"), True, "tool failed",
    )
    second = ExternalToolViewModel("file", "completed", "next.bin", "ok", 0, (), False, None)
    view.render(_state(first, second))
    assert view.history_list.items == [
        "strings / failed / sample.bin", "file / completed / next.bin"
    ]
    assert view.tool_type_label.values["text"] == "Tool種類：strings"
    assert view.target_label.values["text"] == "対象ファイル：sample.bin"
    assert view.exit_code_label.values["text"] == "終了コード：2"
    assert view.repeated_label.values["text"] == "重複実行：あり"
    assert view.error_label.values["text"] == "エラー：tool failed"
    assert view.evidence_list.items == ["source: first", "source: second"]


def test_view_adds_no_raw_output_path_or_execution_dependency():
    source = inspect.getsource(
        importlib.import_module("app.gui.external_tool_view").ExternalToolView
    ).casefold()
    for forbidden in (
        "stdout", "stderr", "target_path", "subprocess", "controller",
        "coordinator", ".execute(", "thread", "asyncio", "print(", "logging",
    ):
        assert forbidden not in source
