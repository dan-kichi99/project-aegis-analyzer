import importlib
import inspect
from dataclasses import replace

from app.presentation import ApplicationPresenter, BudgetViewModel, ToolBudgetPresenter


class FakeWidget:
    def __init__(self, _parent=None, **values):
        self.values = values

    def pack(self, **_values):
        return None

    def configure(self, **values):
        self.values.update(values)


def _view(monkeypatch):
    module = importlib.import_module("app.gui.budget_view")
    for name in ("Frame", "Label"):
        monkeypatch.setattr(module.tk, name, FakeWidget)
    return module, module.BudgetView(object(), ToolBudgetPresenter())


def _state(budget):
    return replace(ApplicationPresenter().initial_state(), budget=budget)


def test_import_is_safe_without_tk_or_mainloop():
    source = inspect.getsource(importlib.import_module("app.gui.budget_view"))
    assert "tk.Tk(" not in source and "mainloop(" not in source


def test_none_clear_and_updated_budget_do_not_leave_previous_values(monkeypatch):
    _module, view = _view(monkeypatch)
    first = BudgetViewModel(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 1.5, 30.0)
    view.render(_state(first))
    assert view.iteration_label.values["text"] == "Iteration：1/2"
    assert view.external_tool_label.values["text"] == "External Tool：13/14"
    view.render(None)
    assert view.iteration_label.values["text"] == "Iteration：未設定"
    assert view.external_tool_label.values["text"] == "External Tool：未設定"
    second = BudgetViewModel(2, 5, 4, 8, 1, 3, 2, 4, 3, 5, 4, 6, 5, 7, 8.5, 60.0)
    view.render(_state(second))
    assert view.iteration_label.values["text"] == "Iteration：2/5"
    assert view.elapsed_time_label.values["text"] == "Elapsed Time：8.5/60.0"
    view.clear()
    assert view.elapsed_time_label.values["text"] == "Elapsed Time：未設定"


def test_all_budget_used_max_fields_are_displayed(monkeypatch):
    _module, view = _view(monkeypatch)
    budget = BudgetViewModel(1, 11, 2, 12, 3, 13, 4, 14, 5, 15, 6, 16, 7, 17, 8.0, 18.0)
    view.render(_state(budget))
    rendered = [label.values["text"] for label, _name in view._labels()]
    assert rendered == [
        "Iteration：1/11", "Action：2/12", "Agent：3/13", "AI：4/14",
        "Local Analysis：5/15", "Execution Feedback：6/16",
        "External Tool：7/17", "Elapsed Time：8.0/18.0",
    ]


def test_budget_view_has_no_mutation_or_execution_dependencies():
    source = inspect.getsource(
        importlib.import_module("app.gui.budget_view").BudgetView
    ).casefold()
    for forbidden in (
        "subprocess", "controller", "coordinator", ".execute(", "thread",
        "asyncio", "print(", "logging", "replace(",
    ):
        assert forbidden not in source
