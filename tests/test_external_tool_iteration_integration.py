from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.challenge.challenge_input import ChallengeInput
from app.external_tools import (
    BaseExternalTool,
    ExternalToolStatus,
    ExternalToolType,
    ToolEvidence,
    ToolResult,
)
from app.iteration import (
    ExternalToolEvidenceFormatter,
    ExternalToolIterationCoordinator,
    ExternalToolIterationExecutionResult,
    ExternalToolIterationResult,
    ExternalToolIterationStatus,
    IterationAction,
    IterationActionStatus,
    IterationActionType,
    IterationBudget,
    IterationBudgetManager,
    IterationOrchestrationStatus,
    IterationOrchestrator,
    IterationRunContext,
    IterationSessionStatus,
    IterationStateManager,
    IterationStopEvaluator,
    IterationUsage,
)
from app.iteration.iteration_budget import BudgetDecision, BudgetDenialReason

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(minutes=1)


class RecordingTool(BaseExternalTool):
    def __init__(self, tool_type=ExternalToolType.STRINGS, result=None, error=None):
        self._tool_type = tool_type
        self.result = result or _tool_result(tool_type=tool_type)
        self.error = error
        self.requests = []

    @property
    def tool_type(self):
        return self._tool_type

    def execute(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result


class EmptyPlanner:
    def __init__(self):
        self.calls = 0

    def plan(self, **_values):
        self.calls += 1
        return ()


def _tool_result(
    *,
    tool_type=ExternalToolType.STRINGS,
    status=ExternalToolStatus.COMPLETED,
    stdout="result",
    evidence=(),
    error_message=None,
):
    return ToolResult(
        tool_type,
        status,
        "tool summary",
        stdout,
        "stderr detail",
        0 if status is ExternalToolStatus.COMPLETED else None,
        tuple(evidence),
        error_message,
    )


def _action(
    target_path,
    *,
    identifier="tool-action",
    tool_type=ExternalToolType.STRINGS,
    status=IterationActionStatus.APPROVED,
    action_type=IterationActionType.RUN_EXTERNAL_TOOL,
    metadata=None,
):
    if metadata is None:
        metadata = {"tool_type": tool_type, "target_path": target_path}
    return IterationAction(
        identifier,
        action_type,
        status,
        "Run tool",
        "Read-only inspection",
        50,
        "Need evidence",
        None,
        True,
        metadata,
    )


def _session(action):
    manager = IterationStateManager()
    session = manager.create_session("session", NOW)
    proposed = replace(action, status=IterationActionStatus.PROPOSED)
    session = manager.add_pending_actions(session, (proposed,), NOW)
    if action.status is IterationActionStatus.APPROVED:
        session = manager.decide_action(session, action.action_id, True, NOW)
    return manager, session


def _coordinator(manager, *tools, max_runs=2):
    return ExternalToolIterationCoordinator(
        state_manager=manager,
        tools=tuple(tools),
        max_runs_per_tool=max_runs,
    )


def test_action_and_result_contracts_are_frozen_and_slotted(tmp_path):
    assert IterationActionType.RUN_EXTERNAL_TOOL.value == "run_external_tool"
    assert tuple(item.value for item in ExternalToolIterationStatus) == (
        "completed",
        "skipped",
        "failed",
        "repeated",
    )
    action = _action((tmp_path / "target").resolve())
    result = ExternalToolIterationResult(
        action.action_id,
        ExternalToolType.STRINGS,
        action.metadata["target_path"],
        ExternalToolIterationStatus.COMPLETED,
        _tool_result(),
        "summary",
        False,
        None,
    )
    _manager, session = _session(action)
    execution = ExternalToolIterationExecutionResult(session, action, result, None)
    for value in (result, execution):
        assert not hasattr(value, "__dict__")
        with pytest.raises(FrozenInstanceError):
            value.__setattr__(next(iter(value.__slots__)), None)
    with pytest.raises(ValueError, match="500"):
        replace(result, summary="x" * 501)
    with pytest.raises(ValueError, match="500"):
        replace(result, error_message="x" * 501)


def test_registration_rejects_duplicates_custom_and_invalid_limit():
    manager = IterationStateManager()
    tool = RecordingTool()
    with pytest.raises(ValueError, match="重複"):
        _coordinator(manager, tool, RecordingTool())
    with pytest.raises(ValueError, match="CUSTOM"):
        _coordinator(manager, RecordingTool(ExternalToolType.CUSTOM))
    for value in (0, True):
        with pytest.raises(ValueError, match="max_runs"):
            _coordinator(manager, max_runs=value)


def test_approved_action_calls_only_selected_adapter_once_with_minimal_request(tmp_path):
    target = (tmp_path / "target.bin").resolve()
    action = _action(
        target,
        metadata={
            "tool_type": "strings",
            "target_path": target,
            "ignored": "must not propagate",
        },
    )
    manager, session = _session(action)
    selected = RecordingTool()
    other = RecordingTool(ExternalToolType.FILE)
    challenge = ChallengeInput("question")

    execution = _coordinator(manager, selected, other).execute_action(
        session=session,
        action_id=action.action_id,
        challenge=challenge,
        working_directory=tmp_path.resolve(),
        updated_at=LATER,
    )

    assert len(selected.requests) == 1
    assert other.requests == []
    request = selected.requests[0]
    assert request.challenge is challenge
    assert request.working_directory == tmp_path.resolve()
    assert dict(request.metadata) == {"target_path": target}
    assert session.current_iteration == 0
    assert action.status is IterationActionStatus.APPROVED
    assert execution.session.status is IterationSessionStatus.ACTIVE
    assert execution.session.pending_actions == ()


@pytest.mark.parametrize(
    "change",
    [
        {"status": IterationActionStatus.PROPOSED},
        {"status": IterationActionStatus.REJECTED},
        {"action_type": IterationActionType.RUN_LOCAL_ANALYSIS},
        {"metadata": {}},
        {"metadata": {"tool_type": "strings"}},
        {"metadata": {"tool_type": "custom", "target_path": Path("C:/x")}},
        {"metadata": {"tool_type": "strings", "target_path": Path("relative")}},
    ],
)
def test_invalid_actions_are_rejected_before_tool_call(tmp_path, change):
    action = replace(_action((tmp_path / "target").resolve()), **change)
    manager, session = _session(action)
    tool = RecordingTool()
    with pytest.raises(ValueError):
        _coordinator(manager, tool).execute_action(
            session=session,
            action_id=action.action_id,
            challenge=ChallengeInput("question"),
            working_directory=tmp_path.resolve(),
            updated_at=LATER,
        )
    assert tool.requests == []


def test_missing_unregistered_inactive_and_old_time_are_rejected(tmp_path):
    action = _action((tmp_path / "target").resolve())
    manager, session = _session(action)
    cases = [
        (_coordinator(manager, RecordingTool()), session, "missing", LATER),
        (_coordinator(manager, RecordingTool(ExternalToolType.FILE)), session, action.action_id, LATER),
        (_coordinator(manager, RecordingTool()), replace(session, status=IterationSessionStatus.STOPPED), action.action_id, LATER),
        (_coordinator(manager, RecordingTool()), session, action.action_id, NOW - timedelta(seconds=1)),
    ]
    for coordinator, candidate, action_id, updated_at in cases:
        with pytest.raises(ValueError):
            coordinator.execute_action(
                session=candidate,
                action_id=action_id,
                challenge=ChallengeInput("question"),
                working_directory=tmp_path.resolve(),
                updated_at=updated_at,
            )


@pytest.mark.parametrize(
    ("tool_status", "iteration_status", "step_status", "completed"),
    [
        (ExternalToolStatus.COMPLETED, ExternalToolIterationStatus.COMPLETED, "completed", True),
        (ExternalToolStatus.SKIPPED, ExternalToolIterationStatus.SKIPPED, "skipped", True),
        (ExternalToolStatus.NOT_RUN, ExternalToolIterationStatus.SKIPPED, "skipped", True),
        (ExternalToolStatus.FAILED, ExternalToolIterationStatus.FAILED, "failed", False),
    ],
)
def test_status_step_and_action_finalization(
    tmp_path, tool_status, iteration_status, step_status, completed
):
    action = _action((tmp_path / "target").resolve())
    manager, session = _session(action)
    tool = RecordingTool(result=_tool_result(status=tool_status, error_message="failed"))
    execution = _coordinator(manager, tool).execute_action(
        session=session,
        action_id=action.action_id,
        challenge=ChallengeInput("question"),
        working_directory=tmp_path.resolve(),
        updated_at=LATER,
    )
    step = execution.step
    assert execution.tool_iteration_result.status is iteration_status
    assert step.status.value == step_status
    assert step.iteration_number == 1
    assert step.external_tool_result is execution.tool_iteration_result
    assert step.agent_result is step.execution_result is None
    assert step.hypotheses == step.open_questions == step.proposed_actions == ()
    assert step.completed_action_ids == ((action.action_id,) if completed else ())
    assert (step.error_message is not None) is (not completed)
    assert execution.session.pending_actions == ()


def test_adapter_exception_becomes_failed_but_interrupts_propagate(tmp_path):
    action = _action((tmp_path / "target").resolve())
    manager, session = _session(action)
    tool = RecordingTool(error=RuntimeError("boom"))
    execution = _coordinator(manager, tool).execute_action(
        session=session,
        action_id=action.action_id,
        challenge=ChallengeInput("question"),
        working_directory=tmp_path.resolve(),
        updated_at=LATER,
    )
    assert execution.tool_iteration_result.status is ExternalToolIterationStatus.FAILED
    assert "RuntimeError: boom" in execution.tool_iteration_result.error_message
    assert execution.session.status is IterationSessionStatus.ACTIVE
    for error in (KeyboardInterrupt(), SystemExit()):
        manager, session = _session(action)
        with pytest.raises(type(error)):
            _coordinator(manager, RecordingTool(error=error)).execute_action(
                session=session,
                action_id=action.action_id,
                challenge=ChallengeInput("question"),
                working_directory=tmp_path.resolve(),
                updated_at=LATER,
            )


def test_repeat_detection_and_per_tool_run_limit(tmp_path):
    first_action = _action((tmp_path / "target").resolve(), identifier="first")
    manager, session = _session(first_action)
    tool = RecordingTool()
    coordinator = _coordinator(manager, tool)
    first = coordinator.execute_action(
        session=session,
        action_id="first",
        challenge=ChallengeInput("question"),
        working_directory=tmp_path.resolve(),
        updated_at=LATER,
    )
    second_action = _action(first_action.metadata["target_path"], identifier="second")
    proposed = replace(second_action, status=IterationActionStatus.PROPOSED)
    session = manager.add_pending_actions(first.session, (proposed,), LATER)
    session = manager.decide_action(session, "second", True, LATER)
    second = coordinator.execute_action(
        session=session,
        action_id="second",
        challenge=ChallengeInput("question"),
        working_directory=tmp_path.resolve(),
        updated_at=LATER + timedelta(seconds=1),
    )
    assert second.tool_iteration_result.status is ExternalToolIterationStatus.REPEATED
    assert second.step.status.value == "skipped"
    assert len(tool.requests) == 2

    third_action = _action(first_action.metadata["target_path"], identifier="third")
    proposed = replace(third_action, status=IterationActionStatus.PROPOSED)
    session = manager.add_pending_actions(second.session, (proposed,), second.session.updated_at)
    session = manager.decide_action(session, "third", True, session.updated_at)
    with pytest.raises(ValueError, match="上限"):
        coordinator.execute_action(
            session=session,
            action_id="third",
            challenge=ChallengeInput("question"),
            working_directory=tmp_path.resolve(),
            updated_at=session.updated_at,
        )
    assert len(tool.requests) == 2


def test_formatter_includes_only_structured_evidence_with_limits(tmp_path):
    evidence = tuple(ToolEvidence("source", "x" * 500, 70) for _ in range(50))
    base = ExternalToolIterationResult(
        "action",
        ExternalToolType.BINWALK,
        (tmp_path / "target").resolve(),
        ExternalToolIterationStatus.COMPLETED,
        _tool_result(
            tool_type=ExternalToolType.BINWALK,
            stdout="SECRET FULL STDOUT",
            evidence=evidence,
        ),
        "summary",
        False,
        None,
    )
    formatted = ExternalToolEvidenceFormatter().format((base,) * 25)
    assert len(formatted) <= 20
    assert sum(map(len, formatted)) <= 10_000
    assert all(len(item) <= 1_000 for item in formatted)
    assert "tool=binwalk" in formatted[0]
    assert "status=completed" in formatted[0]
    assert "summary=summary" in formatted[0]
    assert "evidence[source]=" in formatted[0]
    assert "SECRET FULL STDOUT" not in "".join(formatted)
    assert "正解" not in "".join(formatted)


def test_budget_cost_limits_and_usage_for_external_tool(tmp_path):
    action = _action((tmp_path / "target").resolve())
    _manager, session = _session(action)
    budget_manager = IterationBudgetManager()
    cost = budget_manager.cost_resolver.resolve(action)
    assert cost.external_tool_runs == 1
    assert cost.target_tool is ExternalToolType.STRINGS
    assert cost.ai_calls == cost.agent_runs == cost.local_analyses == 0
    evaluation = budget_manager.evaluate_action(
        session=session,
        action=action,
        budget=IterationBudget(),
        usage=IterationUsage(),
        elapsed_seconds=1.0,
    )
    assert evaluation.decision is BudgetDecision.ALLOW
    projected = evaluation.projected_usage
    assert projected.external_tool_runs_used == 1
    assert projected.tool_counts == {ExternalToolType.STRINGS: 1}
    assert projected.action_counts == {IterationActionType.RUN_EXTERNAL_TOOL: 1}

    denied = budget_manager.evaluate_action(
        session=session,
        action=action,
        budget=IterationBudget(max_external_tool_runs=0),
        usage=IterationUsage(),
        elapsed_seconds=1.0,
    )
    assert denied.primary_reason is BudgetDenialReason.EXTERNAL_TOOL_LIMIT_REACHED


def test_orchestrator_routes_one_external_action_and_consumes_usage(tmp_path):
    action = _action((tmp_path / "target").resolve())
    manager, session = _session(action)
    tool = RecordingTool()
    coordinator = _coordinator(manager, tool)
    planner = EmptyPlanner()
    orchestrator = IterationOrchestrator(
        state_manager=manager,
        action_planner=planner,
        stop_evaluator=IterationStopEvaluator(),
        budget_manager=IterationBudgetManager(),
        local_coordinator=None,
        agent_coordinator=None,
        feedback_coordinator=None,
        external_tool_coordinator=coordinator,
    )
    context = IterationRunContext(
        session,
        IterationUsage(),
        IterationBudget(),
        None,
        None,
        None,
        None,
        None,
        LATER,
        1.0,
        challenge=ChallengeInput("question"),
        working_directory=tmp_path.resolve(),
    )
    result = orchestrator.run_once(context)
    assert result.status in {
        IterationOrchestrationStatus.ACTION_COMPLETED,
        IterationOrchestrationStatus.WAITING_APPROVAL,
    }
    assert result.external_tool_execution is not None
    assert len(tool.requests) == 1
    assert result.usage.external_tool_runs_used == 1
    assert planner.calls == 1


def test_orchestrator_requires_context_and_budget_denial_calls_no_tool(tmp_path):
    action = _action((tmp_path / "target").resolve())
    manager, session = _session(action)
    tool = RecordingTool()
    orchestrator = IterationOrchestrator(
        state_manager=manager,
        action_planner=EmptyPlanner(),
        stop_evaluator=IterationStopEvaluator(),
        budget_manager=IterationBudgetManager(),
        local_coordinator=None,
        agent_coordinator=None,
        feedback_coordinator=None,
        external_tool_coordinator=_coordinator(manager, tool),
    )
    base = IterationRunContext(
        session,
        IterationUsage(),
        IterationBudget(),
        None,
        None,
        None,
        None,
        None,
        LATER,
        1.0,
    )
    with pytest.raises(ValueError, match="challenge"):
        orchestrator.run_once(base)
    denied = orchestrator.run_once(
        replace(
            base,
            budget=IterationBudget(max_external_tool_runs=0),
            challenge=ChallengeInput("question"),
            working_directory=tmp_path.resolve(),
        )
    )
    assert denied.status is IterationOrchestrationStatus.BUDGET_DENIED
    assert tool.requests == []
