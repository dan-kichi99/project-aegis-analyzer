import inspect
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import pytest

from app.agents.agent_aggregate_result import AgentAggregateResult
from app.agents.agent_result import AgentStatus, AgentType
from app.execution.execution_analysis_result import (
    ExecutionAnalysisResult,
    ExecutionFlagCandidate,
    ExecutionOutputSource,
)
from app.iteration.iteration_action import (
    MAX_ACTION_METADATA_KEYS,
    IterationAction,
    IterationActionStatus,
    IterationActionType,
)
from app.iteration.iteration_state import (
    MAX_FLAG_CANDIDATES,
    MAX_HYPOTHESES,
    MAX_OPEN_QUESTIONS,
    MAX_PENDING_ACTIONS,
    MAX_STEPS,
    AnalysisHypothesis,
    HypothesisStatus,
    IterationSessionStatus,
    IterationStep,
    IterationStepStatus,
    IterationStopReason,
    OpenQuestion,
    OpenQuestionStatus,
)
from app.iteration.iteration_state_manager import IterationStateManager

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(minutes=1)


def _hypothesis(identifier="h1", status=HypothesisStatus.OPEN, confidence=50):
    return AnalysisHypothesis(
        identifier,
        "The cipher may be XOR.",
        "crypto",
        confidence,
        status,
        ("evidence-1",),
    )


def _question(identifier="q1", status=OpenQuestionStatus.OPEN, resolution=None):
    return OpenQuestion(identifier, "What is the key?", "crypto", status, resolution)


def _action(
    identifier="a1",
    status=IterationActionStatus.PROPOSED,
    **changes,
):
    values = {
        "action_id": identifier,
        "action_type": IterationActionType.RUN_AGENT,
        "status": status,
        "title": "Run Crypto Agent",
        "description": "Analyze the structured parameters.",
        "priority": 80,
        "reason": "RSA parameters are available.",
        "target_agent": AgentType.CRYPTO,
        "requires_user_approval": True,
        "metadata": {"source": "test"},
    }
    values.update(changes)
    return IterationAction(**values)


def _aggregate(*flags):
    return AgentAggregateResult(
        results=(),
        primary_result=None,
        status=AgentStatus.COMPLETED,
        summary="summary",
        flag_candidates=tuple(flags),
        primary_flag=flags[0] if flags else None,
        confidence=80,
        evidence=(),
        next_actions=(),
        conflicts=(),
        category="Crypto",
    )


def _execution(*flags):
    candidates = tuple(
        ExecutionFlagCandidate(flag, ExecutionOutputSource.STDOUT, index)
        for index, flag in enumerate(flags)
    )
    return ExecutionAnalysisResult(object(), candidates, flags[0] if flags else None, True)


def _step(
    number=1,
    hypotheses=(),
    questions=(),
    actions=(),
    agent_result=None,
    execution_result=None,
    status=IterationStepStatus.COMPLETED,
):
    return IterationStep(
        number,
        status,
        "step summary",
        agent_result,
        execution_result,
        tuple(hypotheses),
        tuple(questions),
        tuple(actions),
        (),
        None,
    )


def test_all_required_enum_values_are_defined():
    assert {item.value for item in IterationSessionStatus} == {
        "active", "completed", "stopped", "failed"
    }
    assert {item.value for item in IterationStepStatus} == {
        "completed", "skipped", "failed"
    }
    assert len(IterationActionType) == 9
    assert IterationActionType.RUN_EXTERNAL_TOOL.value == "run_external_tool"
    assert len(IterationActionStatus) == 6
    assert len(IterationStopReason) == 8
    assert len(HypothesisStatus) == 4
    assert len(OpenQuestionStatus) == 3


@pytest.mark.parametrize("confidence", [0, 100, None])
def test_hypothesis_accepts_confidence_boundaries_and_preserves_evidence(confidence):
    hypothesis = _hypothesis(confidence=confidence)
    assert hypothesis.confidence == confidence
    assert hypothesis.evidence == ("evidence-1",)


@pytest.mark.parametrize("confidence", [-1, 101])
def test_hypothesis_rejects_invalid_confidence(confidence):
    with pytest.raises(ValueError, match="confidence"):
        _hypothesis(confidence=confidence)


def test_empty_ids_questions_titles_and_invalid_priority_are_rejected():
    with pytest.raises(ValueError, match="hypothesis_id"):
        replace(_hypothesis(), hypothesis_id=" ")
    with pytest.raises(ValueError, match="question_id"):
        replace(_question(), question_id="")
    with pytest.raises(ValueError, match="questionは"):
        replace(_question(), question=" ")
    with pytest.raises(ValueError, match="action_id"):
        replace(_action(), action_id="")
    with pytest.raises(ValueError, match="title"):
        replace(_action(), title=" ")
    with pytest.raises(ValueError, match="priority"):
        replace(_action(), priority=101)


def test_resolved_question_requires_resolution_but_blocked_is_distinct():
    with pytest.raises(ValueError, match="resolution"):
        _question(status=OpenQuestionStatus.RESOLVED)
    blocked = _question(status=OpenQuestionStatus.BLOCKED)
    assert blocked.status is OpenQuestionStatus.BLOCKED
    assert blocked.resolution is None


def test_action_metadata_is_copied_and_top_level_read_only():
    metadata = {"source": "before"}
    action = _action(metadata=metadata)
    metadata["source"] = "after"
    assert action.metadata == {"source": "before"}
    with pytest.raises(TypeError):
        action.metadata["source"] = "changed"


def test_action_metadata_and_text_limits_are_enforced():
    with pytest.raises(ValueError, match="metadata"):
        _action(metadata={str(index): index for index in range(MAX_ACTION_METADATA_KEYS + 1)})
    with pytest.raises(ValueError, match="description"):
        _action(description="x" * 1001)
    with pytest.raises(ValueError, match="reason"):
        _action(reason="x" * 1001)


def test_step_validates_number_summary_actions_and_error_limits():
    with pytest.raises(ValueError, match="iteration_number"):
        replace(_step(), iteration_number=0)
    with pytest.raises(ValueError, match="summary"):
        replace(_step(), summary="x" * 501)
    with pytest.raises(ValueError, match="proposed_actions"):
        replace(_step(), proposed_actions=tuple(_action(str(i)) for i in range(21)))
    with pytest.raises(ValueError, match="error_message"):
        replace(_step(), error_message="x" * 501)


def test_all_dtos_are_frozen_and_slotted():
    manager = IterationStateManager()
    values = [_hypothesis(), _question(), _action(), _step(), manager.create_session("s", NOW)]
    for value in values:
        assert not hasattr(value, "__dict__")
        with pytest.raises(FrozenInstanceError):
            value.__setattr__(next(iter(value.__slots__)), "changed")


def test_session_validation_for_dates_primary_flag_and_active_stop_reason():
    session = IterationStateManager().create_session("s", NOW)
    with pytest.raises(ValueError, match="created_at"):
        replace(session, updated_at=NOW - timedelta(seconds=1))
    with pytest.raises(ValueError, match="primary_flag"):
        replace(session, primary_flag="FLAG{missing}")
    with pytest.raises(ValueError, match="ACTIVE"):
        replace(session, stop_reason=IterationStopReason.USER_STOPPED)


def test_create_session_has_exact_initial_state_and_fixed_time():
    session = IterationStateManager().create_session("session-1", NOW)
    assert session.status is IterationSessionStatus.ACTIVE
    assert session.current_iteration == 0
    assert session.steps == session.hypotheses == session.open_questions == ()
    assert session.pending_actions == session.flag_candidates == ()
    assert session.primary_flag is session.stop_reason is None
    assert session.created_at == session.updated_at == NOW


def test_append_step_updates_iteration_and_preserves_original_and_order():
    manager = IterationStateManager()
    original = manager.create_session("s", NOW)
    first = _step(1)
    updated = manager.append_step(original, first, LATER)
    second = _step(2)
    final = manager.append_step(updated, second, LATER + timedelta(minutes=1))
    assert original.current_iteration == 0 and original.steps == ()
    assert updated.current_iteration == 1
    assert final.steps == (first, second)
    assert final.updated_at == LATER + timedelta(minutes=1)


def test_append_rejects_number_gap_and_inactive_session():
    manager = IterationStateManager()
    session = manager.create_session("s", NOW)
    with pytest.raises(ValueError, match="連番"):
        manager.append_step(session, _step(2), LATER)
    stopped = manager.stop_session(session, IterationStopReason.USER_STOPPED, LATER)
    with pytest.raises(ValueError, match="ACTIVE"):
        manager.append_step(stopped, _step(), LATER)


def test_hypotheses_update_by_id_and_keep_original_order():
    manager = IterationStateManager()
    session = manager.append_step(
        manager.create_session("s", NOW),
        _step(hypotheses=(_hypothesis("h1"), _hypothesis("h2"))),
        LATER,
    )
    replacement = replace(
        _hypothesis("h1"),
        confidence=90,
        status=HypothesisStatus.SUPPORTED,
        evidence=("new",),
    )
    session = manager.append_step(
        session,
        _step(2, hypotheses=(replacement, _hypothesis("h3"))),
        LATER + timedelta(minutes=1),
    )
    assert [item.hypothesis_id for item in session.hypotheses] == ["h1", "h2", "h3"]
    assert session.hypotheses[0] is replacement


def test_questions_update_by_id_and_resolved_leave_open_list_but_remain_in_step():
    manager = IterationStateManager()
    session = manager.append_step(
        manager.create_session("s", NOW),
        _step(questions=(_question(),)),
        LATER,
    )
    resolved = _question(status=OpenQuestionStatus.RESOLVED, resolution="key=42")
    step = _step(2, questions=(resolved, _question("q2")))
    session = manager.append_step(session, step, LATER + timedelta(minutes=1))
    assert [item.question_id for item in session.open_questions] == ["q2"]
    assert session.steps[-1].open_questions[0] is resolved


def test_actions_merge_identical_reject_conflict_and_filter_terminal_states():
    manager = IterationStateManager()
    action = _action()
    session = manager.append_step(
        manager.create_session("s", NOW),
        _step(actions=(action, action, _action("done", IterationActionStatus.COMPLETED))),
        LATER,
    )
    assert session.pending_actions == (action,)
    with pytest.raises(ValueError, match="異なる内容"):
        manager.append_step(
            session,
            _step(2, actions=(replace(action, title="different"),)),
            LATER + timedelta(minutes=1),
        )


def test_agent_and_execution_flags_merge_in_order_without_auto_stop():
    manager = IterationStateManager()
    session = manager.append_step(
        manager.create_session("s", NOW),
        _step(
            agent_result=_aggregate("FLAG{a}", "FLAG{same}"),
            execution_result=_execution("FLAG{same}", "flag{a}"),
        ),
        LATER,
    )
    assert session.flag_candidates == ("FLAG{a}", "FLAG{same}", "flag{a}")
    assert session.primary_flag == "FLAG{a}"
    assert session.status is IterationSessionStatus.ACTIVE
    second = manager.append_step(
        session,
        _step(2, agent_result=_aggregate("FLAG{new}")),
        LATER + timedelta(minutes=1),
    )
    assert second.primary_flag == "FLAG{a}"


def test_decide_action_approves_or_rejects_explicitly_and_keeps_original():
    manager = IterationStateManager()
    session = manager.append_step(
        manager.create_session("s", NOW),
        _step(actions=(_action("approve"), _action("reject"))),
        LATER,
    )
    approved = manager.decide_action(
        session, "approve", True, LATER + timedelta(minutes=1)
    )
    assert session.pending_actions[0].status is IterationActionStatus.PROPOSED
    assert approved.pending_actions[0].status is IterationActionStatus.APPROVED
    rejected = manager.decide_action(
        session, "reject", False, LATER + timedelta(minutes=1)
    )
    assert [item.action_id for item in rejected.pending_actions] == ["approve"]
    with pytest.raises(ValueError, match="PROPOSED"):
        manager.decide_action(approved, "approve", True, LATER + timedelta(minutes=2))
    with pytest.raises(ValueError, match="ありません"):
        manager.decide_action(session, "missing", True, LATER + timedelta(minutes=2))


@pytest.mark.parametrize(
    ("reason", "status"),
    [
        (IterationStopReason.FLAG_CANDIDATE_FOUND, IterationSessionStatus.COMPLETED),
        (IterationStopReason.USER_STOPPED, IterationSessionStatus.STOPPED),
        (IterationStopReason.ERROR, IterationSessionStatus.FAILED),
        (IterationStopReason.MAX_ITERATIONS_REACHED, IterationSessionStatus.STOPPED),
    ],
)
def test_stop_session_maps_reason_and_rejects_later_updates(reason, status):
    manager = IterationStateManager()
    session = manager.create_session("s", NOW)
    stopped = manager.stop_session(session, reason, LATER)
    assert stopped.status is status and stopped.stop_reason is reason
    with pytest.raises(ValueError, match="ACTIVE"):
        manager.stop_session(stopped, reason, LATER)
    with pytest.raises(ValueError, match="ACTIVE"):
        manager.decide_action(stopped, "missing", True, LATER)


def test_session_collection_limits_raise_without_dropping_old_data():
    base = IterationStateManager().create_session("s", NOW)
    hypotheses = tuple(_hypothesis(f"h{i}") for i in range(MAX_HYPOTHESES + 1))
    questions = tuple(_question(f"q{i}") for i in range(MAX_OPEN_QUESTIONS + 1))
    actions = tuple(_action(f"a{i}") for i in range(MAX_PENDING_ACTIONS + 1))
    flags = tuple(f"FLAG{{{i}}}" for i in range(MAX_FLAG_CANDIDATES + 1))
    for field, value in (
        ("hypotheses", hypotheses),
        ("open_questions", questions),
        ("pending_actions", actions),
        ("flag_candidates", flags),
    ):
        with pytest.raises(ValueError, match=field):
            replace(base, **{field: value})
    steps = tuple(replace(_step(), iteration_number=i) for i in range(1, MAX_STEPS + 2))
    with pytest.raises(ValueError, match="steps"):
        replace(base, steps=steps, current_iteration=len(steps))


def test_iteration_package_has_no_execution_or_system_dependencies():
    modules = (
        "app.iteration.iteration_action",
        "app.iteration.iteration_state",
        "app.iteration.iteration_state_manager",
    )
    source = "\n".join(
        inspect.getsource(__import__(module, fromlist=["*"])) for module in modules
    ).casefold()
    for forbidden in (
        "subprocess", "openai", "aiclient", "agentrouter", "agentcoordinator",
        "controller", "challengeservice", "eventpublisher", "input(", "print(",
    ):
        assert forbidden not in source
