from dataclasses import FrozenInstanceError, replace

import pytest

from app.presentation import (
    ActionApprovalDecision,
    ActionApprovalPresenter,
    ActionApprovalRequest,
    ActionApprovalState,
    ActionViewModel,
)


def _action(action_id="a1", status="proposed", priority=90):
    return ActionViewModel(
        action_id,
        "review_code",
        status,
        priority,
        f"description-{action_id}",
        True,
    )


def test_decision_enum_and_request_contract_are_frozen_and_slotted():
    assert {item.value for item in ActionApprovalDecision} == {
        "approve",
        "reject",
        "defer",
    }
    request = ActionApprovalRequest("a1", ActionApprovalDecision.APPROVE)
    assert not hasattr(request, "__dict__")
    with pytest.raises(FrozenInstanceError):
        request.action_id = "changed"
    with pytest.raises(ValueError):
        ActionApprovalRequest(" ", ActionApprovalDecision.APPROVE)
    with pytest.raises(ValueError):
        ActionApprovalRequest("x" * 201, ActionApprovalDecision.APPROVE)


def test_state_contract_validates_limits_selection_and_flags():
    presenter = ActionApprovalPresenter()
    state = presenter.initial_state()
    assert not hasattr(state, "__dict__")
    with pytest.raises(FrozenInstanceError):
        state.message = "changed"
    with pytest.raises(ValueError):
        presenter.present_actions(tuple(_action(str(i)) for i in range(101)))
    with pytest.raises(TypeError):
        ActionApprovalState((_action(),), True, _action(), "x", True, True, True)
    with pytest.raises(ValueError):
        ActionApprovalState((_action(),), 1, _action(), "x", True, True, True)
    with pytest.raises(ValueError):
        ActionApprovalState((_action(),), 0, _action("other"), "x", True, True, True)


def test_initial_present_and_selection_preserve_actions_and_order():
    presenter = ActionApprovalPresenter()
    initial = presenter.initial_state()
    assert initial.actions == ()
    assert initial.selected_action is None
    assert initial.message == "承認待ちActionはありません。"
    actions = (_action("first", priority=10), _action("second", priority=90))
    presented = presenter.present_actions(actions)
    selected = presenter.select_action(presented, 1)
    assert presented.actions == actions
    assert presented.selected_index is None
    assert selected.selected_action is actions[1]
    assert selected.can_approve and selected.can_reject and selected.can_defer
    assert actions[0].priority == 10
    cleared = presenter.select_action(selected, None)
    assert cleared.selected_action is None


@pytest.mark.parametrize("index", (-1, 1))
def test_invalid_selection_is_rejected(index):
    state = ActionApprovalPresenter().present_actions((_action(),))
    with pytest.raises(ValueError):
        ActionApprovalPresenter().select_action(state, index)


@pytest.mark.parametrize("index", (True, False))
def test_bool_selection_is_rejected(index):
    state = ActionApprovalPresenter().present_actions((_action(),))
    with pytest.raises(ValueError):
        ActionApprovalPresenter().select_action(state, index)


@pytest.mark.parametrize(
    "status", ("approved", "rejected", "completed", "failed", "skipped")
)
def test_only_proposed_action_can_be_decided(status):
    presenter = ActionApprovalPresenter()
    state = presenter.select_action(presenter.present_actions((_action(status=status),)), 0)
    assert not state.can_approve
    assert not state.can_reject
    assert not state.can_defer
    with pytest.raises(ValueError):
        presenter.build_request(state, ActionApprovalDecision.APPROVE)


@pytest.mark.parametrize("decision", list(ActionApprovalDecision))
def test_each_decision_builds_minimal_request_without_mutating_state(decision):
    presenter = ActionApprovalPresenter()
    action = _action()
    state = presenter.select_action(presenter.present_actions((action,)), 0)
    request = presenter.build_request(state, decision)
    assert request == ActionApprovalRequest("a1", decision)
    assert tuple(request.__slots__) == ("action_id", "decision")
    assert state.selected_action is action
    assert action.status == "proposed"


def test_unselected_request_and_invalid_decision_are_rejected():
    presenter = ActionApprovalPresenter()
    state = presenter.present_actions((_action(),))
    with pytest.raises(ValueError):
        presenter.build_request(state, ActionApprovalDecision.DEFER)
    selected = presenter.select_action(state, 0)
    with pytest.raises(TypeError):
        presenter.build_request(selected, "approve")
    assert replace(selected).selected_action.status == "proposed"
