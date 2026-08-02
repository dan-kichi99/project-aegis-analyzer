import importlib
import inspect

import pytest

from app.presentation import (
    ActionApprovalDecision,
    ActionApprovalPresenter,
    ActionApprovalRequest,
    ActionViewModel,
    IterationViewModel,
)


class FakeWidget:
    def __init__(self, _parent=None, **values):
        self.values = values
        self.items = []
        self.selection = ()
        self.binding = None

    def pack(self, **_values):
        return None

    def configure(self, **values):
        self.values.update(values)

    def bind(self, _event, callback):
        self.binding = callback

    def delete(self, *_values):
        self.items.clear()

    def insert(self, _position, value):
        self.items.append(value)

    def curselection(self):
        return self.selection

    def invoke(self):
        return self.values["command"]()


def _action(action_id="a1", status="proposed", priority=90):
    return ActionViewModel(
        action_id,
        "run_external_tool",
        status,
        priority,
        f"説明-{action_id}",
        True,
    )


def _iteration(actions):
    return IterationViewModel("session", "active", 1, actions, (), (), (), None)


def _view(monkeypatch, callback=None):
    module = importlib.import_module("app.gui.action_approval_view")
    for name in ("Frame", "Label", "Listbox", "Button"):
        monkeypatch.setattr(module.tk, name, FakeWidget)
    return module, module.ActionApprovalView(
        object(), ActionApprovalPresenter(), callback
    )


def _select(view, index):
    view.action_list.selection = (index,)
    view.action_list.binding(None)


def test_import_is_safe_and_does_not_create_root_or_mainloop():
    module = importlib.import_module("app.gui.action_approval_view")
    source = inspect.getsource(module)
    assert "tk.Tk(" not in source
    assert "mainloop(" not in source


def test_none_render_and_clear_remove_previous_actions(monkeypatch):
    _module, view = _view(monkeypatch)
    view.render(_iteration((_action(),)))
    view.render(None)
    assert view.action_list.items == []
    assert view.message_label.values["text"] == "承認待ちActionはありません。"
    assert view.approve_button.values["state"] == "disabled"
    view.render(_iteration((_action(),)))
    view.clear()
    assert view.action_list.items == []


def test_action_list_and_selected_details_preserve_order(monkeypatch):
    _module, view = _view(monkeypatch)
    actions = (_action("low", priority=10), _action("high", priority=90))
    view.render(_iteration(actions))
    assert view.action_list.items == [
        "[10] run_external_tool / proposed / 説明-low",
        "[90] run_external_tool / proposed / 説明-high",
    ]
    _select(view, 1)
    assert view.action_id_label.values["text"] == "Action ID：high"
    assert view.action_type_label.values["text"] == "種別：run_external_tool"
    assert view.status_label.values["text"] == "状態：proposed"
    assert view.priority_label.values["text"] == "priority：90"
    assert view.description_label.values["text"] == "説明：説明-high"
    assert view.approval_required_label.values["text"] == "ユーザー承認：必要"


def test_buttons_only_enable_for_proposed(monkeypatch):
    _module, view = _view(monkeypatch)
    view.render(_iteration((_action(), _action("done", "approved"))))
    _select(view, 0)
    assert view.approve_button.values["state"] == "normal"
    assert view.reject_button.values["state"] == "normal"
    assert view.defer_button.values["state"] == "normal"
    _select(view, 1)
    assert view.approve_button.values["state"] == "disabled"
    assert view.reject_button.values["state"] == "disabled"
    assert view.defer_button.values["state"] == "disabled"


@pytest.mark.parametrize(
    ("button_name", "decision"),
    (
        ("approve_button", ActionApprovalDecision.APPROVE),
        ("reject_button", ActionApprovalDecision.REJECT),
        ("defer_button", ActionApprovalDecision.DEFER),
    ),
)
def test_each_valid_decision_calls_back_once_without_changing_action(
    monkeypatch, button_name, decision
):
    calls = []
    _module, view = _view(monkeypatch, calls.append)
    action = _action()
    view.render(_iteration((action,)))
    _select(view, 0)
    getattr(view, button_name).invoke()
    assert calls == [ActionApprovalRequest("a1", decision)]
    assert view.state.actions == (action,)
    assert view.state.selected_action.status == "proposed"
    assert view.action_list.items == [
        "[90] run_external_tool / proposed / 説明-a1"
    ]


def test_invalid_decision_does_not_call_callback(monkeypatch):
    calls = []
    _module, view = _view(monkeypatch, calls.append)
    view.render(_iteration((_action(status="rejected"),)))
    _select(view, 0)
    view.approve_button.invoke()
    assert calls == []


def test_callback_exception_propagates(monkeypatch):
    def fail(_request):
        raise RuntimeError("callback failure")

    _module, view = _view(monkeypatch, fail)
    view.render(_iteration((_action(),)))
    _select(view, 0)
    with pytest.raises(RuntimeError, match="callback failure"):
        view.approve_button.invoke()


def test_view_has_no_domain_execution_or_sensitive_data_dependencies():
    module = importlib.import_module("app.gui.action_approval_view")
    source = inspect.getsource(module.ActionApprovalView)
    for forbidden in (
        "IterationSession",
        "IterationAction",
        "IterationStateManager",
        "Coordinator",
        "Orchestrator",
        "Controller",
        "ChallengeService",
        "subprocess",
        "thread",
        "asyncio",
        "sleep(",
        ".execute(",
        "metadata",
        "stdout",
        "stderr",
        "api_key",
        "prompt",
        "full_path",
    ):
        assert forbidden not in source
