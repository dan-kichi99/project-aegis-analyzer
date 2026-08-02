import inspect
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from app.agents.agent_aggregate_result import AgentAggregateResult, AgentConflict
from app.agents.agent_result import (
    AgentEvidence,
    AgentResult,
    AgentStatus,
    AgentType,
)
from app.events.analysis_event import AnalysisEvent, AnalysisEventType
from app.external_tools import (
    ExternalToolStatus,
    ExternalToolType,
    ToolEvidence,
    ToolResult,
)
from app.iteration.external_tool_iteration_result import (
    ExternalToolIterationResult,
    ExternalToolIterationStatus,
)
from app.iteration.iteration_action import (
    IterationAction,
    IterationActionStatus,
    IterationActionType,
)
from app.iteration.iteration_budget import IterationBudget
from app.iteration.iteration_state import IterationStep, IterationStepStatus
from app.iteration.iteration_state_manager import IterationStateManager
from app.iteration.iteration_usage import IterationUsage
from app.judge.judge_result import JudgeResult
from app.presentation import (
    ActionViewModel,
    AgentViewModel,
    ApplicationPresenter,
    ApplicationState,
    ApplicationStatus,
    BudgetViewModel,
    ExternalToolViewModel,
    IterationViewModel,
    ProgressViewModel,
    ResultViewModel,
)

NOW = datetime(2026, 8, 2, tzinfo=timezone.utc)


def _event(event_type, metadata=None):
    return AnalysisEvent(event_type, "FLAG{ignored} prompt secret", "phase", NOW, metadata or {})


def _aggregate():
    primary = AgentResult(
        AgentType.REV,
        AgentStatus.COMPLETED,
        "summary",
        "answer",
        "FLAG{candidate}",
        75,
        (),
        (),
        None,
    )
    return AgentAggregateResult(
        (primary,),
        primary,
        AgentStatus.COMPLETED,
        "aggregate",
        tuple(f"FLAG{{{index}}}" for index in range(25)),
        "FLAG{candidate}",
        75,
        tuple(AgentEvidence("source", "x" * 1_100, 70) for _ in range(35)),
        (),
        (AgentConflict("flag", ("a", "b"), (AgentType.REV, AgentType.WEB)),),
        True,
        "Rev",
    )


def _iteration_session(tmp_path):
    manager = IterationStateManager()
    session = manager.create_session("session", NOW)
    action = IterationAction(
        "action",
        IterationActionType.RUN_EXTERNAL_TOOL,
        IterationActionStatus.PROPOSED,
        "title",
        "description",
        50,
        "reason",
        None,
        True,
        {"tool_type": "strings", "target_path": (tmp_path / "secret.bin").resolve()},
    )
    session = manager.add_pending_actions(session, (action,), NOW)
    tool_result = ToolResult(
        ExternalToolType.STRINGS,
        ExternalToolStatus.COMPLETED,
        "tool summary",
        "FULL STDOUT SECRET",
        "FULL STDERR SECRET",
        0,
        (ToolEvidence("strings.stdout", "candidate evidence", 70),),
        None,
    )
    iteration_result = ExternalToolIterationResult(
        "old-action",
        ExternalToolType.STRINGS,
        (tmp_path / "private" / "secret.bin").resolve(),
        ExternalToolIterationStatus.COMPLETED,
        tool_result,
        "tool summary",
        False,
        None,
    )
    step = IterationStep(
        1,
        IterationStepStatus.COMPLETED,
        "step",
        None,
        None,
        (),
        (),
        (),
        ("old-action",),
        None,
        external_tool_result=iteration_result,
    )
    session = manager.append_step(session, step, NOW)
    return session


def test_all_presentation_dtos_are_frozen_and_slotted():
    values = (
        ProgressViewModel(ApplicationStatus.IDLE, "idle", "message", None, None, None),
        ResultViewModel(False, "Unknown", "", None, None, "", (), None),
        AgentViewModel(None, (), "completed", None, (), (), (), False),
        ActionViewModel("id", "type", "status", 1, "description", True),
        IterationViewModel("id", "active", 0, (), (), (), (), None),
        BudgetViewModel(*(0 for _ in range(16))),
        ExternalToolViewModel("file", "completed", "x", "summary", 0, (), False, None),
    )
    state = ApplicationState(values[0], None, None, None, None, ())
    for value in (*values, state):
        assert not hasattr(value, "__dict__")
        with pytest.raises(FrozenInstanceError):
            value.__setattr__(next(iter(value.__slots__)), None)


def test_view_model_limits_are_enforced():
    with pytest.raises(ValueError):
        ProgressViewModel(ApplicationStatus.IDLE, "x" * 101, "", None, None, None)
    with pytest.raises(ValueError):
        ProgressViewModel(ApplicationStatus.IDLE, "", "", 101, None, None)
    with pytest.raises(ValueError):
        ResultViewModel(False, "x", "x" * 20_001, None, None, "", (), None)
    with pytest.raises(ValueError):
        AgentViewModel(None, (), "x", None, ("x",) * 31, (), (), False)


def test_initial_state_and_event_transitions_are_immutable_and_payload_safe():
    presenter = ApplicationPresenter()
    initial = presenter.initial_state()
    assert initial.progress.status is ApplicationStatus.IDLE
    assert initial.result is initial.agent is initial.iteration is initial.budget is None
    assert initial.external_tools == ()

    started_event = _event(AnalysisEventType.ANALYSIS_STARTED)
    started = presenter.apply_event(initial, started_event)
    agent = presenter.apply_event(
        started, _event(AnalysisEventType.AGENT_STARTED, {"agent_type": "rev"})
    )
    completed_agent = presenter.apply_event(agent, _event(AnalysisEventType.AGENT_COMPLETED))
    completed = presenter.apply_event(completed_agent, _event(AnalysisEventType.ANALYSIS_COMPLETED))
    failed = presenter.apply_event(
        initial, _event(AnalysisEventType.ANALYSIS_FAILED, {"error_type": "RuntimeError"})
    )
    assert started.progress.status is ApplicationStatus.ANALYZING
    assert agent.progress.current_agent == "rev"
    assert completed_agent.progress.current_agent is None
    assert completed.progress.status is ApplicationStatus.COMPLETED
    assert failed.progress.status is ApplicationStatus.FAILED
    assert failed.progress.error_type == "RuntimeError"
    assert "FLAG{ignored}" not in started.progress.message
    assert initial.progress.status is ApplicationStatus.IDLE
    assert started_event.metadata == {}


def test_local_solution_event_is_only_waiting_candidate_message():
    state = ApplicationPresenter().apply_event(
        ApplicationPresenter().initial_state(),
        _event(AnalysisEventType.LOCAL_SOLUTION_FOUND, {"flag": "FLAG{secret}"}),
    )
    assert state.progress.status is ApplicationStatus.WAITING_APPROVAL
    assert "候補" in state.progress.message
    assert "FLAG{secret}" not in state.progress.message


def test_judge_and_agent_results_are_presented_with_bounded_candidate_data():
    domain = JudgeResult(
        "Rev",
        "answer" * 5_000,
        "FLAG{candidate}",
        75,
        "reason" * 500,
        next_actions=["x" * 600] * 25,
        agent_result=_aggregate(),
    )
    state = ApplicationPresenter().present_result(
        ApplicationPresenter().initial_state(), domain
    )
    assert state.result.solved
    assert state.result.flag_candidate == "FLAG{candidate}"
    assert state.result.confidence == 75
    assert "候補" in state.result.warning and "提出" in state.result.warning
    assert len(state.result.answer) == 20_000
    assert len(state.result.reason) == 2_000
    assert len(state.result.next_actions) == 20
    assert all(len(item) == 500 for item in state.result.next_actions)
    assert state.agent.primary_agent == "rev"
    assert state.agent.used_fallback
    assert len(state.agent.evidence) == 30
    assert len(state.agent.flag_candidates) == 20
    assert state.agent.conflicts and "flag" in state.agent.conflicts[0]
    assert domain.answer == "answer" * 5_000


def test_iteration_budget_actions_and_external_tools_are_safe_views(tmp_path):
    session = _iteration_session(tmp_path)
    usage = IterationUsage(
        iterations_used=1,
        total_actions_used=2,
        external_tool_runs_used=1,
        elapsed_seconds=3.5,
    )
    state = ApplicationPresenter().present_iteration(
        ApplicationPresenter().initial_state(), session, usage, IterationBudget()
    )
    assert state.iteration.session_id == "session"
    assert state.iteration.current_iteration == 1
    assert len(state.iteration.pending_actions) == 1
    assert state.iteration.pending_actions[0].status == "proposed"
    assert session.pending_actions[0].status is IterationActionStatus.PROPOSED
    assert state.budget.external_tool_runs_used == 1
    assert state.budget.external_tool_runs_max == 10
    assert state.budget.elapsed_seconds == 3.5
    tool = state.external_tools[0]
    assert tool.tool_type == "strings" and tool.status == "completed"
    assert tool.target_name == "secret.bin"
    assert "private" not in tool.target_name
    rendered = repr(tool)
    assert "FULL STDOUT SECRET" not in rendered
    assert "FULL STDERR SECRET" not in rendered
    assert "candidate evidence" in rendered


def test_multiple_external_tool_history_is_preserved(tmp_path):
    session = _iteration_session(tmp_path)
    first = session.steps[0]
    second_result = replace(
        first.external_tool_result,
        action_id="second",
        tool_type=ExternalToolType.FILE,
        target_path=(tmp_path / "second.bin").resolve(),
    )
    second = replace(
        first,
        iteration_number=2,
        completed_action_ids=("second",),
        external_tool_result=second_result,
    )
    session = replace(session, current_iteration=2, steps=(*session.steps, second))
    state = ApplicationPresenter().present_iteration(
        ApplicationPresenter().initial_state(), session
    )
    assert tuple(item.tool_type for item in state.external_tools) == ("strings", "file")


def test_presenter_has_no_io_execution_gui_or_domain_calls():
    source = inspect.getsource(ApplicationPresenter)
    for forbidden in (
        "print(",
        "input(",
        "subprocess",
        "Controller",
        ".analyze(",
        ".execute(",
        "tkinter",
        "PySide",
        "PyQt",
        "thread",
        "asyncio",
        "datetime.now",
        "EventPublisher",
    ):
        assert forbidden not in source
