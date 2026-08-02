from dataclasses import replace

from app.presentation import (
    ApplicationPresenter,
    BudgetViewModel,
    ExternalToolViewModel,
    ToolBudgetPresenter,
)


def _budget():
    return BudgetViewModel(1, 5, 2, 10, 3, 8, 4, 9, 5, 12, 6, 13, 7, 14, 1.5, 60.0)


def _tool():
    return ExternalToolViewModel(
        "strings", "completed", "sample.bin", "summary", 0,
        ("strings.stdout: evidence",), False, None,
    )


def test_presenter_selects_existing_safe_view_models_without_changes():
    presenter = ToolBudgetPresenter()
    initial = ApplicationPresenter().initial_state()
    budget = _budget()
    tools = (_tool(),)
    state = replace(initial, budget=budget, external_tools=tools)
    assert presenter.present_budget(state) is budget
    assert presenter.present_external_tools(state) is tools
    assert state.budget is budget and state.external_tools is tools


def test_presenter_handles_none_and_empty_state():
    presenter = ToolBudgetPresenter()
    initial = ApplicationPresenter().initial_state()
    assert presenter.present_budget(None) is None
    assert presenter.present_external_tools(None) == ()
    assert presenter.present_budget(initial) is None
    assert presenter.present_external_tools(initial) == ()
