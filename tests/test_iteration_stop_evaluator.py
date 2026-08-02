import inspect
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import pytest

from app.iteration.iteration_action import (
    IterationAction,
    IterationActionStatus,
    IterationActionType,
)
from app.iteration.iteration_state import (
    IterationSessionStatus,
    IterationStep,
    IterationStepStatus,
    IterationStopReason,
)
from app.iteration.iteration_state_manager import IterationStateManager
from app.iteration.iteration_stop_evaluator import IterationStopEvaluator
from app.iteration.iteration_stop_result import (
    IterationDecision,
    IterationStopContext,
    IterationStopEvaluation,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(minutes=1)


def _session():
    return IterationStateManager().create_session("session", NOW)


def _action():
    return IterationAction(
        "a1",
        IterationActionType.MANUAL_REVIEW,
        IterationActionStatus.PROPOSED,
        "Review",
        "Review result",
        50,
        "More evidence is needed",
        None,
        True,
        {},
    )


def _step(status=IterationStepStatus.COMPLETED, actions=()):
    return IterationStep(1, status, "summary", None, None, (), (), tuple(actions), (), None)


def _context(session=None, **values):
    arguments = {
        "session": session or _session(),
        "max_iterations": 5,
        "elapsed_seconds": None,
        "time_budget_seconds": None,
        "ai_calls_used": None,
        "ai_call_budget": None,
        "user_requested_stop": False,
        "fatal_error": None,
        "repeated_state": None,
    }
    arguments.update(values)
    return IterationStopContext(**arguments)


def _evaluate(session=None, **values):
    return IterationStopEvaluator().evaluate(_context(session, **values))


def test_decision_enum_context_and_evaluation_dtos():
    assert {item.value for item in IterationDecision} == {
        "continue", "complete", "stop", "fail"
    }
    context = _context()
    evaluation = _evaluate()
    assert context.session.status is IterationSessionStatus.ACTIVE
    assert evaluation.decision is IterationDecision.CONTINUE
    assert not hasattr(context, "__dict__") and not hasattr(evaluation, "__dict__")
    with pytest.raises(FrozenInstanceError):
        context.max_iterations = 2
    with pytest.raises(FrozenInstanceError):
        evaluation.should_stop = True


@pytest.mark.parametrize(
    "changes",
    [
        {"max_iterations": 0},
        {"elapsed_seconds": -0.1},
        {"time_budget_seconds": 0},
        {"ai_calls_used": -1, "ai_call_budget": 1},
        {"ai_calls_used": 0, "ai_call_budget": -1},
        {"ai_calls_used": 0},
        {"ai_call_budget": 1},
        {"fatal_error": "x" * 501},
    ],
)
def test_invalid_context_values_are_rejected(changes):
    with pytest.raises(ValueError):
        _context(**changes)


def test_same_input_is_deterministic_and_does_not_mutate_session():
    session = _session()
    context = _context(session, repeated_state=True)
    first = IterationStopEvaluator().evaluate(context)
    second = IterationStopEvaluator().evaluate(context)
    assert first == second
    assert session.status is IterationSessionStatus.ACTIVE
    assert session.stop_reason is None


def test_fatal_error_and_failed_latest_step_without_actions_fail():
    fatal = _evaluate(fatal_error="secret fatal details")
    assert fatal.decision is IterationDecision.FAIL
    assert fatal.reason is IterationStopReason.ERROR
    assert not fatal.requires_user_confirmation
    assert "secret fatal details" not in fatal.message

    manager = IterationStateManager()
    session = manager.append_step(_session(), _step(IterationStepStatus.FAILED), LATER)
    latest = _evaluate(session)
    assert latest.decision is IterationDecision.FAIL
    assert latest.reason is IterationStopReason.ERROR


def test_failed_latest_step_with_pending_action_does_not_immediately_fail():
    manager = IterationStateManager()
    session = manager.append_step(
        _session(), _step(IterationStepStatus.FAILED, (_action(),)), LATER
    )
    evaluation = _evaluate(session)
    assert evaluation.decision is IterationDecision.CONTINUE


def test_user_stop_is_stop_without_reconfirmation():
    evaluation = _evaluate(user_requested_stop=True)
    assert evaluation.decision is IterationDecision.STOP
    assert evaluation.reason is IterationStopReason.USER_STOPPED
    assert not evaluation.requires_user_confirmation


@pytest.mark.parametrize("used", [2, 3])
def test_ai_budget_at_or_above_limit_stops(used):
    evaluation = _evaluate(ai_calls_used=used, ai_call_budget=2)
    assert evaluation.reason is IterationStopReason.AI_BUDGET_EXCEEDED
    assert evaluation.decision is IterationDecision.STOP


def test_zero_ai_budget_is_already_reached():
    assert _evaluate(ai_calls_used=0, ai_call_budget=0).reason is (
        IterationStopReason.AI_BUDGET_EXCEEDED
    )


@pytest.mark.parametrize("elapsed", [10.0, 11.0])
def test_time_budget_at_or_above_limit_stops(elapsed):
    evaluation = _evaluate(elapsed_seconds=elapsed, time_budget_seconds=10.0)
    assert evaluation.reason is IterationStopReason.TIME_BUDGET_EXCEEDED


def test_max_iteration_at_limit_stops_but_below_can_continue():
    manager = IterationStateManager()
    session = manager.append_step(_session(), _step(actions=(_action(),)), LATER)
    assert _evaluate(session, max_iterations=1).reason is (
        IterationStopReason.MAX_ITERATIONS_REACHED
    )
    assert _evaluate(session, max_iterations=2).decision is IterationDecision.CONTINUE


def test_repeated_state_stops_with_user_confirmation():
    evaluation = _evaluate(repeated_state=True)
    assert evaluation.reason is IterationStopReason.REPEATED_STATE
    assert evaluation.requires_user_confirmation


def test_repeated_state_keeps_action_exhaustion_in_all_matched_conditions():
    manager = IterationStateManager()
    session = manager.append_step(_session(), _step(), LATER)
    evaluation = _evaluate(session, repeated_state=True)
    assert evaluation.reason is IterationStopReason.REPEATED_STATE
    assert evaluation.matched_conditions == (
        IterationStopReason.REPEATED_STATE,
        IterationStopReason.NO_ACTIONS_AVAILABLE,
    )


def test_flag_candidates_or_primary_flag_complete_but_do_not_confirm_correctness():
    session = replace(_session(), flag_candidates=("FLAG{secret}",), primary_flag="FLAG{secret}")
    evaluation = _evaluate(session)
    assert evaluation.decision is IterationDecision.COMPLETE
    assert evaluation.reason is IterationStopReason.FLAG_CANDIDATE_FOUND
    assert evaluation.requires_user_confirmation
    assert "正解を保証しない" in evaluation.message
    assert "FLAG{secret}" not in repr(evaluation)

    primary_only = replace(session, flag_candidates=("FLAG{x}",), primary_flag="FLAG{x}")
    assert _evaluate(primary_only).decision is IterationDecision.COMPLETE


def test_no_actions_after_first_iteration_stops_but_new_session_continues():
    manager = IterationStateManager()
    session = manager.append_step(_session(), _step(), LATER)
    evaluation = _evaluate(session)
    assert evaluation.reason is IterationStopReason.NO_ACTIONS_AVAILABLE
    assert evaluation.requires_user_confirmation
    assert _evaluate().decision is IterationDecision.CONTINUE


def test_pending_action_and_no_other_condition_continue():
    manager = IterationStateManager()
    session = manager.append_step(_session(), _step(actions=(_action(),)), LATER)
    evaluation = _evaluate(session)
    assert evaluation == IterationStopEvaluation(
        IterationDecision.CONTINUE,
        False,
        None,
        "反復解析を継続できます。",
        (),
        False,
    )


def test_all_active_conditions_are_ordered_and_highest_reason_wins():
    manager = IterationStateManager()
    session = manager.append_step(_session(), _step(), LATER)
    session = replace(
        session,
        flag_candidates=("FLAG{candidate}",),
        primary_flag="FLAG{candidate}",
    )
    evaluation = _evaluate(
        session,
        max_iterations=1,
        elapsed_seconds=10,
        time_budget_seconds=10,
        ai_calls_used=1,
        ai_call_budget=1,
        user_requested_stop=True,
        fatal_error="fatal",
        repeated_state=True,
    )
    assert evaluation.reason is IterationStopReason.ERROR
    assert evaluation.decision is IterationDecision.FAIL
    assert evaluation.matched_conditions == (
        IterationStopReason.ERROR,
        IterationStopReason.USER_STOPPED,
        IterationStopReason.AI_BUDGET_EXCEEDED,
        IterationStopReason.TIME_BUDGET_EXCEEDED,
        IterationStopReason.MAX_ITERATIONS_REACHED,
        IterationStopReason.REPEATED_STATE,
        IterationStopReason.FLAG_CANDIDATE_FOUND,
    )


@pytest.mark.parametrize(
    ("reason", "expected_status", "expected_decision"),
    [
        (
            IterationStopReason.FLAG_CANDIDATE_FOUND,
            IterationSessionStatus.COMPLETED,
            IterationDecision.COMPLETE,
        ),
        (
            IterationStopReason.USER_STOPPED,
            IterationSessionStatus.STOPPED,
            IterationDecision.STOP,
        ),
        (
            IterationStopReason.ERROR,
            IterationSessionStatus.FAILED,
            IterationDecision.FAIL,
        ),
    ],
)
def test_existing_terminal_session_is_preserved_without_reevaluation(
    reason,
    expected_status,
    expected_decision,
):
    stopped = IterationStateManager().stop_session(_session(), reason, LATER)
    assert stopped.status is expected_status
    evaluation = _evaluate(
        stopped,
        fatal_error="new error",
        user_requested_stop=True,
        ai_calls_used=1,
        ai_call_budget=1,
    )
    assert evaluation.decision is expected_decision
    assert evaluation.reason is reason
    assert evaluation.matched_conditions == (reason,)


def test_failed_session_without_reason_defaults_to_error():
    failed = replace(
        _session(),
        status=IterationSessionStatus.FAILED,
        stop_reason=None,
    )
    evaluation = _evaluate(failed)
    assert evaluation.decision is IterationDecision.FAIL
    assert evaluation.reason is IterationStopReason.ERROR


def test_evaluator_has_no_mutation_runtime_measurement_or_external_dependencies():
    modules = (
        "app.iteration.iteration_stop_result",
        "app.iteration.iteration_stop_evaluator",
    )
    source = "\n".join(
        inspect.getsource(__import__(module, fromlist=["*"])) for module in modules
    ).casefold()
    for forbidden in (
        "stop_session", "iterationstatemanager", "subprocess", "openai", "aiclient",
        "agentrouter", "agentcoordinator", ".analyze(", ".generate(", "datetime",
        "monotonic", "perf_counter", "time.time", "sleep(", "eventpublisher",
        "controller", "challengeservice", "input(", "print(",
    ):
        assert forbidden not in source
