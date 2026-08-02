import inspect
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import pytest

from app.agents.agent import BaseAgent
from app.agents.agent_input import AgentInput
from app.agents.agent_result import AgentEvidence, AgentResult, AgentStatus, AgentType
from app.agents.agent_route_result import AgentRouteResult, AgentRouteStatus
from app.agents.agent_router import AgentRouter
from app.challenge.challenge_input import ChallengeInput
from app.iteration.agent_iteration_coordinator import (
    AgentIterationCoordinator,
    AgentIterationExecutionResult,
    AgentIterationRequest,
)
from app.iteration.agent_iteration_result import (
    AgentIterationResult,
    AgentIterationStatus,
)
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

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


class RecordingAgent(BaseAgent):
    def __init__(self, agent_type=AgentType.REV, result=None, error=None):
        self._agent_type = agent_type
        self.result = result or _agent_result(agent_type=agent_type)
        self.error = error
        self.inputs = []

    @property
    def agent_type(self):
        return self._agent_type

    def analyze(self, agent_input):
        self.inputs.append(agent_input)
        if self.error is not None:
            raise self.error
        return self.result


def _agent_result(
    *,
    agent_type=AgentType.REV,
    status=AgentStatus.COMPLETED,
    summary="agent summary",
    flag=None,
    evidence=(),
    next_actions=(),
    error_message=None,
):
    return AgentResult(
        agent_type=agent_type,
        status=status,
        summary=summary,
        answer="answer",
        flag_candidate=flag,
        confidence=80,
        evidence=evidence,
        next_actions=next_actions,
        error_message=error_message,
    )


def _action(
    identifier="run-rev",
    *,
    status=IterationActionStatus.APPROVED,
    action_type=IterationActionType.RUN_AGENT,
    target=AgentType.REV,
    metadata=None,
):
    return IterationAction(
        identifier,
        action_type,
        status,
        "Run agent",
        "Run one specialist",
        80,
        "Approved analysis",
        target,
        True,
        {"agent_type": "rev"} if metadata is None else metadata,
    )


def _session(action=None, *, approve=False):
    manager = IterationStateManager()
    action = action or _action()
    session = manager.create_session("session", NOW)
    step = IterationStep(
        1,
        IterationStepStatus.COMPLETED,
        "planned",
        None,
        None,
        (),
        (),
        (action,),
        (),
        None,
    )
    session = manager.append_step(session, step, NOW + timedelta(minutes=1))
    if approve:
        session = manager.decide_action(
            session, action.action_id, True, NOW + timedelta(minutes=1)
        )
    return session


def _input(category="Unknown"):
    return AgentInput(
        ChallengeInput("question"),
        category,
        "context",
        ("knowledge",),
        {"source": "test"},
    )


def _coordinator(agent=None, *, max_runs=2, router=None):
    agent = agent or RecordingAgent()
    return AgentIterationCoordinator(
        state_manager=IterationStateManager(),
        router=router or AgentRouter((agent,)),
        max_runs_per_agent=max_runs,
    )


def _execute(coordinator, session=None, agent_input=None, minutes=2):
    return coordinator.execute_action(
        session=session or _session(),
        action_id="run-rev",
        agent_input=agent_input or _input(),
        updated_at=NOW + timedelta(minutes=minutes),
    )


def _add_action(session, action, minute):
    action = replace(action, status=IterationActionStatus.PROPOSED)
    step = IterationStep(
        session.current_iteration + 1,
        IterationStepStatus.COMPLETED,
        "next",
        None,
        None,
        (),
        (),
        (action,),
        (),
        None,
    )
    manager = IterationStateManager()
    session = manager.append_step(session, step, NOW + timedelta(minutes=minute))
    return manager.decide_action(
        session, action.action_id, True, NOW + timedelta(minutes=minute)
    )


def test_agent_iteration_dtos_are_frozen_slotted_and_validate_text_limits():
    session = _session()
    request = AgentIterationRequest(session, session.pending_actions[0], _input())
    route = AgentRouteResult(
        "Unknown", AgentType.REV, AgentRouteStatus.COMPLETED, _agent_result(), None, None
    )
    result = AgentIterationResult(
        "run-rev", AgentType.REV, AgentIterationStatus.COMPLETED,
        route, route.result, "summary", False, None,
    )
    assert tuple(AgentIterationStatus) == (
        AgentIterationStatus.COMPLETED,
        AgentIterationStatus.SKIPPED,
        AgentIterationStatus.FAILED,
        AgentIterationStatus.REPEATED,
    )
    for value in (request, result):
        assert not hasattr(value, "__dict__")
        with pytest.raises(FrozenInstanceError):
            value.__setattr__(next(iter(value.__slots__)), None)
    with pytest.raises(ValueError, match="summary"):
        replace(result, summary="x" * 501)
    with pytest.raises(ValueError, match="error_message"):
        replace(result, error_message="x" * 501)


def test_coordinator_configuration_is_explicit_and_validated():
    coordinator = _coordinator()
    assert coordinator.max_runs_per_agent == 2
    assert coordinator.router.agents[0].agent_type is AgentType.REV
    for value in (0, -1):
        with pytest.raises(ValueError, match="1以上"):
            _coordinator(max_runs=value)
    source = inspect.getsource(__import__(
        "app.iteration.agent_iteration_coordinator", fromlist=["*"]
    )).casefold()
    assert "singleton" not in source and "global " not in source


@pytest.mark.parametrize(
    ("action", "match"),
    [
        (_action(status=IterationActionStatus.PROPOSED), "APPROVED"),
        (_action(status=IterationActionStatus.REJECTED), "pending_actions"),
        (_action(action_type=IterationActionType.RUN_LOCAL_ANALYSIS), "RUN_AGENT"),
        (_action(target=None), "target_agent"),
        (_action(metadata={}), "agent_type"),
        (_action(metadata={"agent_type": "crypto"}), "一致"),
        (_action(metadata={"agent_type": "invalid"}), "有効"),
    ],
)
def test_action_validation_rejects_invalid_action(action, match):
    with pytest.raises(ValueError, match=match):
        _execute(_coordinator(), _session(action))


def test_validation_rejects_missing_unregistered_inactive_and_old_time():
    coordinator = _coordinator()
    session = _session()
    with pytest.raises(ValueError, match="1件"):
        coordinator.execute_action(
            session=session, action_id="missing", agent_input=_input(),
            updated_at=NOW + timedelta(minutes=2),
        )
    with pytest.raises(ValueError, match="登録"):
        _execute(_coordinator(agent=RecordingAgent(AgentType.CRYPTO)), session)
    stopped = IterationStateManager().stop_session(
        session, IterationStopReason.USER_STOPPED, NOW + timedelta(minutes=2)
    )
    with pytest.raises(ValueError, match="ACTIVE"):
        _execute(coordinator, stopped, minutes=3)
    with pytest.raises(ValueError, match="過去"):
        _execute(coordinator, session, minutes=0)


def test_agent_input_copy_preserves_original_category_context_knowledge_and_metadata():
    agent = RecordingAgent()
    original = _input("Misc")
    _execute(_coordinator(agent), agent_input=original)
    assert len(agent.inputs) == 1
    routed = agent.inputs[0]
    assert routed is not original
    assert routed.category == original.category == "Misc"
    assert routed.target_agent is AgentType.REV
    assert original.target_agent is None
    assert routed.challenge is original.challenge
    assert routed.context == original.context
    assert routed.local_knowledge == original.local_knowledge
    assert dict(routed.metadata) == dict(original.metadata)


@pytest.mark.parametrize(
    ("agent_status", "iteration_status", "step_status"),
    [
        (AgentStatus.COMPLETED, AgentIterationStatus.COMPLETED, IterationStepStatus.COMPLETED),
        (AgentStatus.SKIPPED, AgentIterationStatus.SKIPPED, IterationStepStatus.SKIPPED),
        (AgentStatus.FAILED, AgentIterationStatus.FAILED, IterationStepStatus.FAILED),
    ],
)
def test_route_status_is_converted_and_action_is_finalized(
    agent_status, iteration_status, step_status
):
    agent = RecordingAgent(result=_agent_result(status=agent_status, error_message="failed"))
    result = _execute(_coordinator(agent))
    assert isinstance(result, AgentIterationExecutionResult)
    assert len(agent.inputs) == 1
    assert result.agent_iteration_result.status is iteration_status
    assert result.step.status is step_status
    assert result.session.pending_actions == ()
    assert result.session.status is IterationSessionStatus.ACTIVE
    expected = () if agent_status is AgentStatus.FAILED else ("run-rev",)
    assert result.step.completed_action_ids == expected
    assert result.step.error_message == ("failed" if agent_status is AgentStatus.FAILED else None)


class RouteOnlyRouter:
    def __init__(self, route=None, error=None):
        self.route = route
        self.error = error
        self.calls = []

    def has_agent(self, agent_type):
        return True

    def route_agent(self, agent_type, agent_input):
        self.calls.append((agent_type, agent_input))
        if self.error is not None:
            raise self.error
        return self.route


@pytest.mark.parametrize("route_status", [AgentRouteStatus.NO_AGENT, AgentRouteStatus.FAILED])
def test_missing_route_result_becomes_failed_agent_result(route_status):
    route = AgentRouteResult(
        "Unknown", AgentType.REV, route_status, None, "RuntimeError", "detail"
    )
    router = RouteOnlyRouter(route=route)
    result = _execute(_coordinator(router=router))
    agent_result = result.agent_iteration_result.agent_result
    assert len(router.calls) == 1
    assert result.agent_iteration_result.status is AgentIterationStatus.FAILED
    assert agent_result is not None and agent_result.status is AgentStatus.FAILED
    assert agent_result.summary == "反復Agent解析中にエラーが発生しました。"
    assert result.step.error_message == "detail"


def test_router_exception_is_recorded_once_without_retry():
    router = RouteOnlyRouter(error=RuntimeError("x" * 600))
    result = _execute(_coordinator(router=router))
    assert len(router.calls) == 1
    assert result.step.status is IterationStepStatus.FAILED
    assert result.step.error_message.startswith("RuntimeError:")
    assert len(result.step.error_message) == 500


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit()])
def test_base_exceptions_are_not_caught(error):
    router = RouteOnlyRouter(error=error)
    with pytest.raises(type(error)):
        _execute(_coordinator(router=router))


def test_step_wraps_single_result_and_merges_flag_without_stopping_session():
    evidence = (AgentEvidence("binary", "strcmp", 90),)
    agent = RecordingAgent(
        result=_agent_result(
            flag="FLAG{agent}", evidence=evidence, next_actions=("inspect",)
        )
    )
    original = _session()
    action = original.pending_actions[0]
    result = _execute(_coordinator(agent), original)
    aggregate = result.step.agent_result
    assert aggregate is not None
    assert aggregate.category == "Unknown"
    assert aggregate.results == (agent.result,)
    assert aggregate.primary_result is agent.result
    assert aggregate.flag_candidates == ("FLAG{agent}",)
    assert aggregate.primary_flag == "FLAG{agent}"
    assert aggregate.confidence == 80
    assert aggregate.evidence[0].source == "[rev] binary"
    assert aggregate.next_actions == ("inspect",)
    assert aggregate.conflicts == () and not aggregate.used_fallback
    assert result.step.execution_result is None
    assert result.step.hypotheses == result.step.open_questions == ()
    assert result.step.proposed_actions == ()
    assert result.session.flag_candidates == ("FLAG{agent}",)
    assert result.session.primary_flag == "FLAG{agent}"
    assert result.session.status is IterationSessionStatus.ACTIVE
    assert result.session.stop_reason is None
    assert original.pending_actions == (action,)
    assert action.status is IterationActionStatus.APPROVED


def test_identical_result_is_repeated_but_changed_fingerprint_is_not():
    agent = RecordingAgent()
    coordinator = _coordinator(agent)
    first = _execute(coordinator)
    second_action = _action("run-rev-2")
    session = _add_action(first.session, second_action, 3)
    second = coordinator.execute_action(
        session=session, action_id="run-rev-2", agent_input=_input(),
        updated_at=NOW + timedelta(minutes=4),
    )
    assert second.agent_iteration_result.status is AgentIterationStatus.REPEATED
    assert second.agent_iteration_result.repeated
    assert second.step.status is IterationStepStatus.SKIPPED
    assert second.step.completed_action_ids == ("run-rev-2",)
    assert second.session.pending_actions == ()
    assert second.session.status is IterationSessionStatus.ACTIVE

    changed = RecordingAgent(result=replace(agent.result, summary="changed"))
    third_action = _action("run-rev-3")
    third_session = _add_action(first.session, third_action, 3)
    third = AgentIterationCoordinator(
        state_manager=IterationStateManager(), router=AgentRouter((changed,)),
        max_runs_per_agent=2,
    ).execute_action(
        session=third_session, action_id="run-rev-3", agent_input=_input(),
        updated_at=NOW + timedelta(minutes=4),
    )
    assert third.agent_iteration_result.status is AgentIterationStatus.COMPLETED
    assert not third.agent_iteration_result.repeated


@pytest.mark.parametrize(
    "field,value",
    [
        ("flag_candidate", "FLAG{other}"),
        ("evidence", (AgentEvidence("other", "detail", 40),)),
        ("next_actions", ("other",)),
    ],
)
def test_fingerprint_detects_flag_evidence_and_next_action_changes(field, value):
    first_agent = RecordingAgent()
    first = _execute(_coordinator(first_agent))
    session = _add_action(first.session, _action("run-rev-2"), 3)
    changed = RecordingAgent(result=replace(first_agent.result, **{field: value}))
    result = _coordinator(changed).execute_action(
        session=session, action_id="run-rev-2", agent_input=_input(),
        updated_at=NOW + timedelta(minutes=4),
    )
    assert result.agent_iteration_result.status is AgentIterationStatus.COMPLETED


def test_run_limit_counts_completed_failed_and_skipped_but_is_per_agent():
    first = _execute(_coordinator(RecordingAgent()))
    session = _add_action(first.session, _action("run-rev-2"), 3)
    skipped = RecordingAgent(result=_agent_result(status=AgentStatus.SKIPPED))
    second = _coordinator(skipped).execute_action(
        session=session, action_id="run-rev-2", agent_input=_input(),
        updated_at=NOW + timedelta(minutes=4),
    )
    third_session = _add_action(second.session, _action("run-rev-3"), 5)
    third_agent = RecordingAgent()
    with pytest.raises(ValueError, match="上限"):
        _coordinator(third_agent).execute_action(
            session=third_session, action_id="run-rev-3", agent_input=_input(),
            updated_at=NOW + timedelta(minutes=6),
        )
    assert third_agent.inputs == []

    crypto_action = _action(
        "run-crypto", target=AgentType.CRYPTO, metadata={"agent_type": "crypto"}
    )
    crypto_session = _add_action(second.session, crypto_action, 5)
    crypto = RecordingAgent(AgentType.CRYPTO)
    result = _coordinator(crypto).execute_action(
        session=crypto_session, action_id="run-crypto", agent_input=_input(),
        updated_at=NOW + timedelta(minutes=6),
    )
    assert result.agent_iteration_result.status is AgentIterationStatus.COMPLETED


def test_unexecuted_pending_action_does_not_count_and_completed_action_cannot_repeat():
    session = _session()
    agent = RecordingAgent()
    result = _execute(_coordinator(agent, max_runs=1), session)
    assert len(agent.inputs) == 1
    with pytest.raises(ValueError, match="1件"):
        _coordinator(agent).execute_action(
            session=result.session, action_id="run-rev", agent_input=_input(),
            updated_at=NOW + timedelta(minutes=3),
        )


def test_agent_iteration_scope_has_no_automatic_or_external_operations():
    modules = (
        "app.iteration.agent_iteration_result",
        "app.iteration.agent_iteration_coordinator",
    )
    source = "\n".join(
        inspect.getsource(__import__(module, fromlist=["*"])) for module in modules
    ).casefold()
    for forbidden in (
        "subprocess", "openai", "aiclient", "agentcoordinator",
        "iterationactionplanner", "iterationstopevaluator", "eventpublisher",
        "controller", "challengeservice", "datetime.now", "time.", "input(",
        "\nprint(", "\nopen(", "write_text", "write_bytes",
    ):
        assert forbidden not in source
