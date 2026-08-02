import inspect
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import pytest

from app.agents.agent import BaseAgent
from app.agents.agent_input import AgentInput
from app.agents.agent_result import AgentResult, AgentStatus, AgentType
from app.agents.agent_router import AgentRouter
from app.challenge.challenge_input import ChallengeInput
from app.execution.execution_analysis_result import ExecutionAnalysisResult
from app.execution.execution_result import ExecutionStatus, PythonExecutionResult
from app.iteration.agent_iteration_coordinator import AgentIterationCoordinator
from app.iteration.execution_feedback_coordinator import ExecutionFeedbackCoordinator
from app.iteration.iteration_action import (
    IterationAction,
    IterationActionStatus,
    IterationActionType,
)
from app.iteration.iteration_action_planner import IterationActionPlanner
from app.iteration.iteration_budget import IterationBudget
from app.iteration.iteration_budget_manager import IterationBudgetManager
from app.iteration.iteration_coordinator import IterationCoordinator
from app.iteration.iteration_orchestration_result import (
    IterationOrchestrationStatus,
    IterationRunContext,
)
from app.iteration.iteration_orchestrator import IterationOrchestrator
from app.iteration.iteration_state import (
    AnalysisHypothesis,
    HypothesisStatus,
    IterationSessionStatus,
    IterationStep,
    IterationStepStatus,
    IterationStopReason,
)
from app.iteration.iteration_state_manager import IterationStateManager
from app.iteration.iteration_stop_evaluator import IterationStopEvaluator
from app.iteration.iteration_usage import IterationUsage
from app.iteration.local_analysis_executor import (
    BaseLocalAnalysisExecutor,
    HypothesisReviewExecutor,
)
from app.iteration.local_analysis_result import LocalAnalysisResult, LocalAnalysisStatus

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(minutes=1)


def _action(
    identifier="local",
    *,
    action_type=IterationActionType.RUN_LOCAL_ANALYSIS,
    status=IterationActionStatus.APPROVED,
    priority=50,
    target=None,
    metadata=None,
):
    if metadata is None:
        if action_type is IterationActionType.RUN_LOCAL_ANALYSIS:
            metadata = {"analysis_type": "recording"}
        elif target is not None:
            metadata = {"agent_type": target.value}
        else:
            metadata = {}
    return IterationAction(
        identifier,
        action_type,
        status,
        "Action",
        "Description",
        priority,
        "Reason",
        target,
        True,
        metadata,
    )


class RecordingLocalExecutor(BaseLocalAnalysisExecutor):
    def __init__(self, status=LocalAnalysisStatus.COMPLETED):
        self.status = status
        self.requests = []

    @property
    def analysis_type(self):
        return "recording"

    def execute(self, request):
        self.requests.append(request)
        return LocalAnalysisResult(
            request.action.action_id,
            self.analysis_type,
            self.status,
            "local result",
            (),
            (),
            (),
            (),
            "failed" if self.status is LocalAnalysisStatus.FAILED else None,
        )


class RecordingAgent(BaseAgent):
    def __init__(self, status=AgentStatus.COMPLETED):
        self.status = status
        self.inputs = []

    @property
    def agent_type(self):
        return AgentType.REV

    def analyze(self, agent_input):
        self.inputs.append(agent_input)
        return AgentResult(
            AgentType.REV,
            self.status,
            "agent result",
            "answer",
            None,
            70,
            (),
            (),
            "failed" if self.status is AgentStatus.FAILED else None,
        )


class RecordingPlanner:
    def __init__(self, actions=()):
        self.actions = tuple(actions)
        self.calls = []

    def plan(self, **values):
        self.calls.append(values)
        return self.actions


def _dependencies(*, planner=None, local_status=LocalAnalysisStatus.COMPLETED, agent_status=AgentStatus.COMPLETED):
    manager = IterationStateManager()
    local_executor = RecordingLocalExecutor(local_status)
    agent = RecordingAgent(agent_status)
    orchestrator = IterationOrchestrator(
        state_manager=manager,
        action_planner=planner or RecordingPlanner(),
        stop_evaluator=IterationStopEvaluator(),
        budget_manager=IterationBudgetManager(),
        local_coordinator=IterationCoordinator(
            state_manager=manager,
            executors=(local_executor, HypothesisReviewExecutor()),
        ),
        agent_coordinator=AgentIterationCoordinator(
            state_manager=manager, router=AgentRouter((agent,))
        ),
        feedback_coordinator=ExecutionFeedbackCoordinator(state_manager=manager),
    )
    return orchestrator, manager, local_executor, agent


def _session(actions=()):
    manager = IterationStateManager()
    session = manager.create_session("session", NOW)
    proposed = tuple(replace(action, status=IterationActionStatus.PROPOSED) for action in actions)
    session = manager.add_pending_actions(session, proposed, NOW)
    for action in actions:
        if action.status is IterationActionStatus.APPROVED:
            session = manager.decide_action(session, action.action_id, True, NOW)
    return session


def _agent_input():
    return AgentInput(ChallengeInput("question"), "Unknown", "context", (), {})


def _execution(*, started=True, flags=()):
    execution = PythonExecutionResult(
        ExecutionStatus.COMPLETED if started else ExecutionStatus.REJECTED,
        started,
        "stdout",
        "stderr",
        0 if started else None,
        False,
        0.01,
        None,
        "message",
        False,
        True,
    )
    return ExecutionAnalysisResult(execution, tuple(flags), None, started)


def _context(
    session=None,
    *,
    usage=None,
    budget=None,
    agent_input=None,
    execution=None,
    source_index=None,
    **changes,
):
    values = {
        "session": session or _session(),
        "usage": usage or IterationUsage(),
        "budget": budget or IterationBudget(),
        "judge_result": None,
        "agent_result": None,
        "execution_result": execution,
        "execution_source_index": source_index,
        "agent_input": agent_input,
        "updated_at": LATER,
        "elapsed_seconds": 1.0,
        "user_requested_stop": False,
        "fatal_error": None,
        "repeated_state": None,
    }
    values.update(changes)
    return IterationRunContext(**values)


def test_composition_uses_all_injected_dependencies_without_internal_state():
    planner = RecordingPlanner()
    orchestrator, manager, _, _ = _dependencies(planner=planner)
    assert orchestrator.state_manager is manager
    assert orchestrator.action_planner is planner
    assert not hasattr(orchestrator, "session")
    assert not hasattr(orchestrator, "usage")


def test_context_and_result_are_frozen_slotted_and_validate_limits():
    context = _context()
    orchestrator, *_ = _dependencies()
    result = orchestrator.run_once(context)
    for value in (context, result):
        assert not hasattr(value, "__dict__")
        with pytest.raises(FrozenInstanceError):
            value.__setattr__(next(iter(value.__slots__)), None)
    with pytest.raises(ValueError, match="elapsed"):
        replace(context, elapsed_seconds=-1)
    with pytest.raises(ValueError, match="source_index"):
        replace(context, execution_source_index=-1)
    with pytest.raises(ValueError, match="fatal_error"):
        replace(context, fatal_error="x" * 501)
    with pytest.raises(ValueError, match="message"):
        replace(result, message="x" * 501)
    with pytest.raises(ValueError, match="同時に1件"):
        replace(
            result,
            local_execution=object(),
            agent_execution=object(),
        )


@pytest.mark.parametrize(
    ("changes", "status", "session_status"),
    [
        ({"fatal_error": "fatal"}, IterationOrchestrationStatus.FAILED, IterationSessionStatus.FAILED),
        ({"user_requested_stop": True}, IterationOrchestrationStatus.STOPPED, IterationSessionStatus.STOPPED),
        ({"elapsed_seconds": 300.0}, IterationOrchestrationStatus.STOPPED, IterationSessionStatus.STOPPED),
    ],
)
def test_initial_stop_prevents_planning_and_applies_unconfirmed_stop(changes, status, session_status):
    planner = RecordingPlanner((_action(status=IterationActionStatus.PROPOSED),))
    orchestrator, *_ = _dependencies(planner=planner)
    result = orchestrator.run_once(_context(**changes))
    assert result.status is status
    assert result.session.status is session_status
    assert planner.calls == []
    assert result.usage == IterationUsage()


def test_initial_ai_and_iteration_budget_stops_before_action():
    planner = RecordingPlanner((_action(status=IterationActionStatus.PROPOSED),))
    orchestrator, manager, _, _ = _dependencies(planner=planner)
    ai_stop = orchestrator.run_once(
        _context(budget=IterationBudget(max_ai_calls=0))
    )
    assert ai_stop.stop_evaluation.reason is IterationStopReason.AI_BUDGET_EXCEEDED
    assert ai_stop.session.status is IterationSessionStatus.STOPPED
    assert planner.calls == []

    session = manager.create_session("iteration", NOW)
    session = manager.append_step(
        session,
        IterationStep(1, IterationStepStatus.COMPLETED, "initial", None, None, (), (), (), (), None),
        NOW,
    )
    maxed = orchestrator.run_once(_context(session, budget=IterationBudget(max_iterations=1)))
    assert maxed.stop_evaluation.reason is IterationStopReason.MAX_ITERATIONS_REACHED
    assert maxed.session.status is IterationSessionStatus.STOPPED
    assert planner.calls == []


def test_flag_stop_requires_confirmation_and_does_not_mutate_session():
    session = replace(_session(), flag_candidates=("FLAG{candidate}",), primary_flag="FLAG{candidate}")
    planner = RecordingPlanner()
    orchestrator, *_ = _dependencies(planner=planner)
    result = orchestrator.run_once(_context(session))
    assert result.status is IterationOrchestrationStatus.WAITING_APPROVAL
    assert result.stop_evaluation.requires_user_confirmation
    assert result.session.status is IterationSessionStatus.ACTIVE
    assert planner.calls == []


def test_planning_adds_proposed_without_iteration_or_usage_and_waits():
    action = _action("planned", status=IterationActionStatus.PROPOSED)
    planner = RecordingPlanner((action,))
    orchestrator, *_ = _dependencies(planner=planner)
    context = _context()
    result = orchestrator.run_once(context)
    assert len(planner.calls) == 1
    assert planner.calls[0]["existing_actions"] == ()
    assert result.status is IterationOrchestrationStatus.WAITING_APPROVAL
    assert result.planned_actions == (action,)
    assert result.session.pending_actions == (action,)
    assert result.session.current_iteration == 0
    assert result.session.updated_at == LATER
    assert result.usage is context.usage
    assert action.status is IterationActionStatus.PROPOSED


def test_state_manager_pending_addition_deduplicates_and_rejects_conflict():
    manager = IterationStateManager()
    action = _action("planned", status=IterationActionStatus.PROPOSED)
    session = manager.add_pending_actions(_session(), (action,), LATER)
    same = manager.add_pending_actions(session, (action,), LATER)
    assert same.pending_actions == (action,)
    assert same.current_iteration == 0
    with pytest.raises(ValueError, match="異なる内容"):
        manager.add_pending_actions(session, (replace(action, title="different"),), LATER)
    with pytest.raises(ValueError, match="PROPOSED"):
        manager.add_pending_actions(session, (_action("approved"),), LATER)


def test_completed_action_id_is_filtered_from_new_plans():
    completed = _action("done", status=IterationActionStatus.PROPOSED)
    manager = IterationStateManager()
    session = manager.append_step(
        _session(),
        IterationStep(1, IterationStepStatus.COMPLETED, "done", None, None, (), (), (), ("done",), None),
        NOW,
    )
    planner = RecordingPlanner((completed,))
    orchestrator, *_ = _dependencies(planner=planner)
    result = orchestrator.run_once(_context(session))
    assert result.planned_actions == ()
    assert result.session.pending_actions == ()


def test_no_actions_initial_evaluation_is_deferred_until_after_planning():
    manager = IterationStateManager()
    session = manager.append_step(
        _session(),
        IterationStep(
            1,
            IterationStepStatus.COMPLETED,
            "previous",
            None,
            None,
            (),
            (),
            (),
            ("previous-action",),
            None,
        ),
        NOW,
    )
    action = _action("new-action", status=IterationActionStatus.PROPOSED)
    planner = RecordingPlanner((action,))
    orchestrator, *_ = _dependencies(planner=planner)

    result = orchestrator.run_once(_context(session))

    assert len(planner.calls) == 1
    assert result.stop_evaluation.reason is None
    assert result.status is IterationOrchestrationStatus.WAITING_APPROVAL
    assert result.planned_actions == (action,)
    assert result.session.pending_actions == (action,)


def test_no_actions_is_confirmed_only_after_planner_returns_nothing():
    manager = IterationStateManager()
    session = manager.append_step(
        _session(),
        IterationStep(
            1,
            IterationStepStatus.COMPLETED,
            "previous",
            None,
            None,
            (),
            (),
            (),
            ("previous-action",),
            None,
        ),
        NOW,
    )
    planner = RecordingPlanner()
    orchestrator, *_ = _dependencies(planner=planner)

    result = orchestrator.run_once(_context(session))

    assert len(planner.calls) == 1
    assert result.stop_evaluation.reason is IterationStopReason.NO_ACTIONS_AVAILABLE
    assert result.stop_evaluation.requires_user_confirmation
    assert result.status is IterationOrchestrationStatus.WAITING_APPROVAL
    assert result.session.status is IterationSessionStatus.ACTIVE


def test_real_planner_accepts_approved_pending_as_same_action_definition():
    hypothesis = AnalysisHypothesis(
        "h1", "statement", "test", 80, HypothesisStatus.OPEN, ()
    )
    generated = IterationActionPlanner().plan(
        agent_result=None,
        judge_result=None,
        execution_result=None,
        hypotheses=(hypothesis,),
        open_questions=(),
    )[0]
    session = replace(
        _session((replace(generated, status=IterationActionStatus.APPROVED),)),
        hypotheses=(hypothesis,),
    )
    orchestrator, *_ = _dependencies(planner=IterationActionPlanner())
    result = orchestrator.run_once(_context(session))
    assert result.selected_action.action_id == generated.action_id


def test_highest_priority_then_action_id_executes_only_one_and_keeps_others():
    low = _action("z-low", priority=50)
    tie_b = _action("b-high", priority=90)
    tie_a = _action("a-high", priority=90)
    session = _session((low, tie_b, tie_a))
    orchestrator, _, executor, _ = _dependencies()
    result = orchestrator.run_once(_context(session))
    assert result.selected_action.action_id == "a-high"
    assert len(executor.requests) == 1
    assert {action.action_id for action in result.session.pending_actions} == {"z-low", "b-high"}
    assert result.session.current_iteration == 1
    assert result.usage.total_actions_used == result.usage.iterations_used == 1


def test_budget_denial_keeps_action_usage_and_coordinators_untouched():
    action = _action()
    session = _session((action,))
    orchestrator, _, executor, agent = _dependencies()
    context = _context(session, budget=IterationBudget(max_local_analyses=0))
    result = orchestrator.run_once(context)
    assert result.status is IterationOrchestrationStatus.BUDGET_DENIED
    assert result.budget_evaluation is not None
    assert result.session.pending_actions == (action,)
    assert result.usage is context.usage
    assert executor.requests == [] and agent.inputs == []


@pytest.mark.parametrize(
    ("local_status", "expected"),
    [
        (LocalAnalysisStatus.COMPLETED, IterationOrchestrationStatus.ACTION_COMPLETED),
        (LocalAnalysisStatus.SKIPPED, IterationOrchestrationStatus.ACTION_SKIPPED),
        (LocalAnalysisStatus.FAILED, IterationOrchestrationStatus.ACTION_FAILED),
    ],
)
def test_local_dispatches_once_and_consumes_even_failed_or_skipped(local_status, expected):
    keep = _action("keep", status=IterationActionStatus.PROPOSED)
    session = _session((_action(), keep))
    orchestrator, _, executor, _ = _dependencies(local_status=local_status)
    result = orchestrator.run_once(_context(session))
    assert result.status is expected
    assert len(executor.requests) == 1
    assert result.local_execution is not None
    assert result.agent_execution is result.feedback_execution is None
    assert result.usage.local_analyses_used == 1
    assert result.usage.total_actions_used == 1


@pytest.mark.parametrize("agent_status", list(AgentStatus))
def test_agent_dispatch_requires_input_runs_once_and_consumes(agent_status):
    action = _action(
        "agent",
        action_type=IterationActionType.RUN_AGENT,
        target=AgentType.REV,
    )
    session = _session((action, _action("keep", status=IterationActionStatus.PROPOSED)))
    orchestrator, _, _, agent = _dependencies(agent_status=agent_status)
    with pytest.raises(ValueError, match="agent_input"):
        orchestrator.run_once(_context(session))
    assert agent.inputs == []
    result = orchestrator.run_once(_context(session, agent_input=_agent_input()))
    assert len(agent.inputs) == 1
    assert result.agent_execution is not None
    assert result.usage.agent_runs_used == result.usage.ai_calls_used == 1


def test_feedback_dispatch_requires_structured_input_and_consumes_failed_feedback():
    action = _action(
        "feedback",
        action_type=IterationActionType.ANALYZE_EXECUTION_OUTPUT,
        metadata={"source_index": 0},
    )
    session = _session((action, _action("keep", status=IterationActionStatus.PROPOSED)))
    orchestrator, *_ = _dependencies()
    with pytest.raises(ValueError, match="execution_result"):
        orchestrator.run_once(_context(session))
    with pytest.raises(ValueError, match="source_index"):
        orchestrator.run_once(_context(session, execution=_execution()))
    result = orchestrator.run_once(
        _context(session, execution=_execution(started=False), source_index=0)
    )
    assert result.feedback_execution is not None
    assert result.status is IterationOrchestrationStatus.ACTION_FAILED
    assert result.usage.execution_feedbacks_used == 1


@pytest.mark.parametrize(
    "action_type",
    [
        IterationActionType.REVIEW_CODE,
        IterationActionType.EXECUTE_APPROVED_CODE,
        IterationActionType.MANUAL_REVIEW,
        IterationActionType.REQUEST_USER_INPUT,
        IterationActionType.STOP,
    ],
)
def test_unsupported_action_is_budget_denied_and_not_executed(action_type):
    action = _action("unsupported", action_type=action_type, metadata={})
    session = _session((action,))
    orchestrator, _, executor, agent = _dependencies()
    result = orchestrator.run_once(_context(session))
    assert result.status is IterationOrchestrationStatus.BUDGET_DENIED
    assert result.session.pending_actions == (action,)
    assert executor.requests == [] and agent.inputs == []


def test_phase5_scope_has_no_loop_retry_global_state_or_external_operations():
    modules = (
        "app.iteration.iteration_orchestration_result",
        "app.iteration.iteration_orchestrator",
    )
    source = "\n".join(
        inspect.getsource(__import__(module, fromlist=["*"])) for module in modules
    ).casefold()
    for forbidden in (
        "while ", "run_once(", "subprocess", "openai", "datetime.now", "sleep(",
        "eventpublisher", "controller", "challengeservice", "resultformatter",
        "decide_action", "submit", "singleton", "\nprint(", "\nopen(",
    ):
        if forbidden == "run_once(":
            assert source.count(forbidden) == 1
        else:
            assert forbidden not in source
