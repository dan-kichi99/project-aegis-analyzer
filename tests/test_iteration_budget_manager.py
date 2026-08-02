import inspect
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from math import inf, nan
from types import MappingProxyType

import pytest

from app.agents.agent_result import AgentType
from app.iteration.iteration_action import (
    IterationAction,
    IterationActionStatus,
    IterationActionType,
)
from app.iteration.iteration_budget import (
    BudgetDecision,
    BudgetDenialReason,
    IterationActionCost,
    IterationBudget,
)
from app.iteration.iteration_budget_manager import (
    InvalidActionCostError,
    IterationActionCostResolver,
    IterationBudgetManager,
    UnsupportedActionError,
)
from app.iteration.iteration_state import IterationStopReason
from app.iteration.iteration_state_manager import IterationStateManager
from app.iteration.iteration_usage import IterationUsage

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def _action(
    action_type=IterationActionType.RUN_LOCAL_ANALYSIS,
    *,
    status=IterationActionStatus.APPROVED,
    target=None,
    metadata=None,
):
    if metadata is None:
        metadata = {"agent_type": target.value} if target is not None else {}
    return IterationAction(
        f"action-{action_type.value}",
        action_type,
        status,
        "Action",
        "Description",
        50,
        "Reason",
        target,
        True,
        metadata,
    )


def _agent_action(agent_type=AgentType.REV, **changes):
    return _action(
        IterationActionType.RUN_AGENT,
        target=agent_type,
        metadata={"agent_type": agent_type.value},
        **changes,
    )


def _session():
    return IterationStateManager().create_session("session", NOW)


def _evaluate(action=None, *, budget=None, usage=None, elapsed=0.0, session=None):
    return IterationBudgetManager().evaluate_action(
        session=session or _session(),
        action=action or _action(),
        budget=budget or IterationBudget(),
        usage=usage or IterationUsage(),
        elapsed_seconds=elapsed,
    )


def test_budget_defaults_are_frozen_slotted_and_valid():
    budget = IterationBudget()
    assert budget == IterationBudget(10, 20, 4, 4, 10, 10, 300.0, 2)
    assert not hasattr(budget, "__dict__")
    with pytest.raises(FrozenInstanceError):
        budget.max_iterations = 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_iterations", 0),
        ("max_total_actions", 0),
        ("max_agent_runs", -1),
        ("max_ai_calls", -1),
        ("max_local_analyses", -1),
        ("max_execution_feedbacks", -1),
        ("max_elapsed_seconds", 0),
        ("max_elapsed_seconds", inf),
        ("max_runs_per_agent", 0),
        ("max_iterations", True),
        ("max_elapsed_seconds", False),
    ],
)
def test_budget_rejects_invalid_limits_and_bool(field, value):
    with pytest.raises(ValueError):
        replace(IterationBudget(), **{field: value})


def test_usage_defaults_are_frozen_slotted_and_mappings_are_defensive():
    actions = {IterationActionType.RUN_AGENT: 1}
    agents = {AgentType.REV: 1}
    usage = IterationUsage(action_counts=actions, agent_counts=agents)
    actions.clear()
    agents.clear()
    assert usage.iterations_used == usage.total_actions_used == 0
    assert usage.action_counts == {IterationActionType.RUN_AGENT: 1}
    assert usage.agent_counts == {AgentType.REV: 1}
    assert isinstance(usage.action_counts, MappingProxyType)
    assert not hasattr(usage, "__dict__")
    with pytest.raises(TypeError):
        usage.action_counts[IterationActionType.RUN_AGENT] = 2
    with pytest.raises(FrozenInstanceError):
        usage.iterations_used = 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("iterations_used", -1),
        ("total_actions_used", True),
        ("elapsed_seconds", -1),
        ("elapsed_seconds", nan),
        ("elapsed_seconds", inf),
        ("elapsed_seconds", False),
        ("action_counts", {"run_agent": 1}),
        ("action_counts", {IterationActionType.RUN_AGENT: -1}),
        ("agent_counts", {"rev": 1}),
        ("agent_counts", {AgentType.REV: -1}),
    ],
)
def test_usage_rejects_invalid_values_and_mapping_entries(field, value):
    with pytest.raises(ValueError):
        replace(IterationUsage(), **{field: value})


def test_cost_dto_is_frozen_slotted_and_rejects_invalid_values():
    cost = IterationActionCost(1, 1, 0, 0, 1, 0, None)
    assert not hasattr(cost, "__dict__")
    with pytest.raises(FrozenInstanceError):
        cost.actions = 2
    with pytest.raises(ValueError):
        replace(cost, actions=-1)
    with pytest.raises(ValueError):
        replace(cost, ai_calls=True)
    with pytest.raises(ValueError):
        replace(cost, target_agent="rev")


def test_cost_resolver_returns_formal_costs():
    resolver = IterationActionCostResolver()
    assert resolver.resolve(_action()) == IterationActionCost(1, 1, 0, 0, 1, 0, None)
    assert resolver.resolve(_agent_action()) == IterationActionCost(
        1, 1, 1, 1, 0, 0, AgentType.REV
    )
    feedback = _action(IterationActionType.ANALYZE_EXECUTION_OUTPUT)
    assert resolver.resolve(feedback) == IterationActionCost(1, 1, 0, 0, 0, 1, None)


@pytest.mark.parametrize(
    "action_type",
    [
        IterationActionType.REVIEW_CODE,
        IterationActionType.EXECUTE_APPROVED_CODE,
        IterationActionType.REQUEST_USER_INPUT,
        IterationActionType.MANUAL_REVIEW,
        IterationActionType.STOP,
    ],
)
def test_cost_resolver_rejects_unsupported_actions(action_type):
    with pytest.raises(UnsupportedActionError):
        IterationActionCostResolver().resolve(_action(action_type))


@pytest.mark.parametrize(
    "action",
    [
        _action(IterationActionType.RUN_AGENT),
        _action(IterationActionType.RUN_AGENT, target=AgentType.REV, metadata={}),
        _action(
            IterationActionType.RUN_AGENT,
            target=AgentType.REV,
            metadata={"agent_type": "crypto"},
        ),
        _action(
            IterationActionType.RUN_AGENT,
            target=AgentType.REV,
            metadata={"agent_type": "unknown-agent"},
        ),
    ],
)
def test_run_agent_cost_requires_matching_structured_agent_type(action):
    with pytest.raises(InvalidActionCostError):
        IterationActionCostResolver().resolve(action)


def test_cost_resolver_does_not_infer_agent_from_natural_language():
    action = replace(
        _action(IterationActionType.RUN_AGENT),
        title="Run Rev agent",
        description="Use crypto and rev",
    )
    with pytest.raises(InvalidActionCostError):
        IterationActionCostResolver().resolve(action)


@pytest.mark.parametrize(
    "action",
    [
        _action(),
        _agent_action(),
        _action(IterationActionType.ANALYZE_EXECUTION_OUTPUT),
    ],
)
def test_supported_active_approved_action_is_allowed_with_projection(action):
    session = _session()
    usage = IterationUsage()
    evaluation = _evaluate(action, session=session, usage=usage, elapsed=1.0)
    assert evaluation.decision is BudgetDecision.ALLOW
    assert evaluation.allowed
    assert evaluation.primary_reason is None
    assert evaluation.matched_reasons == ()
    assert evaluation.projected_usage is not None
    assert evaluation.projected_usage.total_actions_used == 1
    assert usage.total_actions_used == 0
    assert action.status is IterationActionStatus.APPROVED
    assert session.current_iteration == 0


def test_evaluation_dto_enforces_consistent_decision_and_message_limit():
    allowed = _evaluate()
    with pytest.raises(ValueError, match="ALLOW"):
        replace(allowed, allowed=False)
    denied = replace(
        allowed,
        decision=BudgetDecision.DENY,
        allowed=False,
        primary_reason=BudgetDenialReason.TIME_LIMIT_REACHED,
        matched_reasons=(BudgetDenialReason.TIME_LIMIT_REACHED,),
        projected_usage=None,
    )
    with pytest.raises(ValueError, match="DENY"):
        replace(denied, primary_reason=None)
    with pytest.raises(ValueError, match="先頭"):
        replace(
            denied,
            matched_reasons=(BudgetDenialReason.ACTION_NOT_APPROVED,),
        )
    with pytest.raises(ValueError, match="message"):
        replace(allowed, message="x" * 501)


def test_denial_reasons_are_complete_and_in_priority_order():
    manager = IterationBudgetManager()
    usage = IterationUsage(
        iterations_used=1,
        total_actions_used=1,
        agent_runs_used=1,
        ai_calls_used=1,
        agent_counts={AgentType.REV: 1},
    )
    session = IterationStateManager().stop_session(
        _session(), IterationStopReason.USER_STOPPED, NOW
    )
    action = _agent_action(status=IterationActionStatus.PROPOSED)
    evaluation = manager.evaluate_action(
        session=session,
        action=action,
        budget=IterationBudget(
            max_iterations=1,
            max_total_actions=1,
            max_agent_runs=1,
            max_ai_calls=1,
            max_local_analyses=0,
            max_execution_feedbacks=0,
            max_elapsed_seconds=1,
            max_runs_per_agent=1,
        ),
        usage=usage,
        elapsed_seconds=1,
    )
    assert evaluation.matched_reasons == (
        BudgetDenialReason.SESSION_NOT_ACTIVE,
        BudgetDenialReason.ACTION_NOT_APPROVED,
        BudgetDenialReason.TIME_LIMIT_REACHED,
        BudgetDenialReason.ITERATION_LIMIT_REACHED,
        BudgetDenialReason.TOTAL_ACTION_LIMIT_REACHED,
        BudgetDenialReason.AI_CALL_LIMIT_REACHED,
        BudgetDenialReason.AGENT_RUN_LIMIT_REACHED,
        BudgetDenialReason.AGENT_TYPE_LIMIT_REACHED,
    )
    assert evaluation.primary_reason is BudgetDenialReason.SESSION_NOT_ACTIVE
    assert evaluation.projected_usage is None
    assert usage.total_actions_used == 1


@pytest.mark.parametrize(
    ("action", "budget", "reason"),
    [
        (_agent_action(), IterationBudget(max_agent_runs=0), BudgetDenialReason.AGENT_RUN_LIMIT_REACHED),
        (_agent_action(), IterationBudget(max_ai_calls=0), BudgetDenialReason.AI_CALL_LIMIT_REACHED),
        (_agent_action(), IterationBudget(max_runs_per_agent=1), None),
        (_action(), IterationBudget(max_local_analyses=0), BudgetDenialReason.LOCAL_ANALYSIS_LIMIT_REACHED),
        (
            _action(IterationActionType.ANALYZE_EXECUTION_OUTPUT),
            IterationBudget(max_execution_feedbacks=0),
            BudgetDenialReason.EXECUTION_FEEDBACK_LIMIT_REACHED,
        ),
    ],
)
def test_zero_and_exact_count_boundaries(action, budget, reason):
    evaluation = _evaluate(action, budget=budget)
    if reason is None:
        assert evaluation.allowed
    else:
        assert reason in evaluation.matched_reasons


def test_projected_count_equal_to_limit_allowed_and_plus_one_denied():
    budget = IterationBudget(max_iterations=1, max_total_actions=1, max_local_analyses=1)
    assert _evaluate(budget=budget).allowed
    usage = IterationUsage(
        iterations_used=1,
        total_actions_used=1,
        local_analyses_used=1,
    )
    denied = _evaluate(budget=budget, usage=usage)
    assert BudgetDenialReason.ITERATION_LIMIT_REACHED in denied.matched_reasons
    assert BudgetDenialReason.TOTAL_ACTION_LIMIT_REACHED in denied.matched_reasons
    assert BudgetDenialReason.LOCAL_ANALYSIS_LIMIT_REACHED in denied.matched_reasons


def test_time_boundary_and_elapsed_validation():
    budget = IterationBudget(max_elapsed_seconds=10)
    assert _evaluate(budget=budget, elapsed=9.999).allowed
    assert _evaluate(budget=budget, elapsed=10).primary_reason is BudgetDenialReason.TIME_LIMIT_REACHED
    assert _evaluate(budget=budget, elapsed=11).primary_reason is BudgetDenialReason.TIME_LIMIT_REACHED
    usage = IterationUsage(elapsed_seconds=5)
    with pytest.raises(ValueError, match="過去"):
        _evaluate(budget=budget, usage=usage, elapsed=4)
    for value in (-1, nan, inf, True):
        with pytest.raises(ValueError):
            _evaluate(elapsed=value)


def test_unsupported_and_invalid_cost_become_deterministic_denials():
    unsupported = _evaluate(_action(IterationActionType.EXECUTE_APPROVED_CODE))
    invalid = _evaluate(_action(IterationActionType.RUN_AGENT))
    assert unsupported.primary_reason is BudgetDenialReason.UNSUPPORTED_ACTION
    assert invalid.primary_reason is BudgetDenialReason.INVALID_COST
    assert _evaluate(_action(IterationActionType.RUN_AGENT)) == invalid


def test_consume_updates_all_usage_counters_and_mappings_without_mutation():
    manager = IterationBudgetManager()
    original = manager.create_usage()
    action = _agent_action()
    cost = manager.cost_resolver.resolve(action)
    updated = manager.consume(
        usage=original,
        action=action,
        cost=cost,
        elapsed_seconds=2.5,
    )
    assert updated.iterations_used == 1
    assert updated.total_actions_used == 1
    assert updated.agent_runs_used == 1
    assert updated.ai_calls_used == 1
    assert updated.local_analyses_used == 0
    assert updated.execution_feedbacks_used == 0
    assert updated.elapsed_seconds == 2.5
    assert updated.action_counts == {IterationActionType.RUN_AGENT: 1}
    assert updated.agent_counts == {AgentType.REV: 1}
    assert original == IterationUsage()

    crypto = _agent_action(AgentType.CRYPTO)
    separated = manager.consume(
        usage=updated,
        action=crypto,
        cost=manager.cost_resolver.resolve(crypto),
        elapsed_seconds=3,
    )
    assert separated.agent_counts == {AgentType.REV: 1, AgentType.CRYPTO: 1}


def test_consume_local_and_feedback_counts_and_replaces_elapsed():
    manager = IterationBudgetManager()
    local = _action()
    usage = manager.consume(
        usage=IterationUsage(elapsed_seconds=1),
        action=local,
        cost=manager.cost_resolver.resolve(local),
        elapsed_seconds=4,
    )
    feedback = _action(IterationActionType.ANALYZE_EXECUTION_OUTPUT)
    usage = manager.consume(
        usage=usage,
        action=feedback,
        cost=manager.cost_resolver.resolve(feedback),
        elapsed_seconds=6,
    )
    assert usage.local_analyses_used == 1
    assert usage.execution_feedbacks_used == 1
    assert usage.elapsed_seconds == 6
    assert usage.total_actions_used == usage.iterations_used == 2


def test_consume_rejects_nonstandard_cost_and_old_elapsed():
    manager = IterationBudgetManager()
    action = _action()
    with pytest.raises(ValueError, match="標準Cost"):
        manager.consume(
            usage=IterationUsage(),
            action=action,
            cost=IterationActionCost(1, 1, 0, 0, 0, 0, None),
            elapsed_seconds=0,
        )
    with pytest.raises(ValueError, match="過去"):
        manager.consume(
            usage=IterationUsage(elapsed_seconds=2),
            action=action,
            cost=manager.cost_resolver.resolve(action),
            elapsed_seconds=1,
        )


def test_budget_manager_scope_is_pure_and_has_no_global_usage_or_execution():
    modules = (
        "app.iteration.iteration_budget",
        "app.iteration.iteration_usage",
        "app.iteration.iteration_budget_manager",
    )
    source = "\n".join(
        inspect.getsource(__import__(module, fromlist=["*"])) for module in modules
    ).casefold()
    for forbidden in (
        "subprocess", "openai", "aiclient", ".analyze(", ".execute(",
        "coordinator", "eventpublisher", "controller", "challengeservice",
        "datetime.now", "time.", "sleep(", "input(", "\nprint(", "\nopen(",
        "stop_session", "decide_action", "complete_action", "singleton",
    ):
        assert forbidden not in source
    manager = IterationBudgetManager()
    assert manager.create_usage() is not manager.create_usage()
