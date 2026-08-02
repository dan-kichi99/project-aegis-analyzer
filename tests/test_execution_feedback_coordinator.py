import inspect
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import pytest

from app.execution.execution_analysis_result import (
    ExecutionAnalysisResult,
    ExecutionFlagCandidate,
    ExecutionOutputSource,
)
from app.execution.execution_result import ExecutionStatus, PythonExecutionResult
from app.iteration.execution_feedback_coordinator import (
    ExecutionFeedbackCoordinator,
    ExecutionFeedbackExecutionResult,
    ExecutionFeedbackRequest,
)
from app.iteration.execution_feedback_result import (
    MAX_FEEDBACK_ITEMS,
    ExecutionFeedbackResult,
    ExecutionFeedbackStatus,
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
    OpenQuestion,
    OpenQuestionStatus,
)
from app.iteration.iteration_state_manager import IterationStateManager

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def _action(
    identifier="feedback-0",
    *,
    status=IterationActionStatus.APPROVED,
    action_type=IterationActionType.ANALYZE_EXECUTION_OUTPUT,
    metadata=None,
):
    return IterationAction(
        identifier,
        action_type,
        status,
        "Analyze output",
        "Record existing analysis",
        70,
        "Approved feedback",
        None,
        True,
        {"source_index": 0} if metadata is None else metadata,
    )


def _analysis(
    *,
    status=ExecutionStatus.COMPLETED,
    started=True,
    exit_code=0,
    timed_out=False,
    truncated=False,
    stdout="ordinary stdout",
    stderr="ordinary stderr",
    flags=(),
    successful=None,
):
    execution = PythonExecutionResult(
        status=status,
        started=started,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        timed_out=timed_out,
        duration_seconds=0.01,
        failure_reason=None,
        message="result",
        output_truncated=truncated,
        cleanup_succeeded=True,
    )
    candidates = tuple(
        ExecutionFlagCandidate(flag, ExecutionOutputSource.STDOUT, index)
        for index, flag in enumerate(flags)
    )
    return ExecutionAnalysisResult(
        execution=execution,
        flag_candidates=candidates,
        primary_flag=candidates[0].flag if candidates else None,
        successful_execution=(
            status is ExecutionStatus.COMPLETED
            and exit_code == 0
            and not timed_out
            if successful is None
            else successful
        ),
    )


def _session(action=None):
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
    return manager.append_step(session, step, NOW + timedelta(minutes=1))


def _coordinator():
    return ExecutionFeedbackCoordinator(state_manager=IterationStateManager())


def _apply(session=None, analysis=None, *, source_index=0, action_id="feedback-0", minute=2):
    return _coordinator().apply_feedback(
        session=session or _session(),
        action_id=action_id,
        execution_analysis=analysis or _analysis(),
        source_index=source_index,
        updated_at=NOW + timedelta(minutes=minute),
    )


def _add_action(session, action, minute):
    proposed = replace(action, status=IterationActionStatus.PROPOSED)
    step = IterationStep(
        session.current_iteration + 1,
        IterationStepStatus.COMPLETED,
        "next",
        None,
        None,
        (),
        (),
        (proposed,),
        (),
        None,
    )
    manager = IterationStateManager()
    session = manager.append_step(session, step, NOW + timedelta(minutes=minute))
    return manager.decide_action(
        session, proposed.action_id, True, NOW + timedelta(minutes=minute)
    )


def test_feedback_dtos_are_frozen_slotted_and_status_is_complete():
    session = _session()
    action = session.pending_actions[0]
    request = ExecutionFeedbackRequest(session, action, _analysis(), 0)
    result = ExecutionFeedbackResult(
        action.action_id,
        0,
        ExecutionFeedbackStatus.COMPLETED,
        "summary",
        request.execution_analysis,
        (),
        (),
        (),
        False,
        None,
    )
    assert tuple(ExecutionFeedbackStatus) == (
        ExecutionFeedbackStatus.COMPLETED,
        ExecutionFeedbackStatus.SKIPPED,
        ExecutionFeedbackStatus.FAILED,
        ExecutionFeedbackStatus.REPEATED,
    )
    for value in (request, result):
        assert not hasattr(value, "__dict__")
        with pytest.raises(FrozenInstanceError):
            value.__setattr__(next(iter(value.__slots__)), None)
    with pytest.raises(ValueError, match="source_index"):
        replace(request, source_index=-1)


def test_feedback_result_validates_text_collections_and_proposed_actions():
    result = _apply().feedback_result
    with pytest.raises(ValueError, match="summary"):
        replace(result, summary="x" * 501)
    with pytest.raises(ValueError, match="error_message"):
        replace(result, error_message="x" * 501)
    with pytest.raises(ValueError, match="flag_candidates"):
        replace(result, flag_candidates=tuple(str(i) for i in range(MAX_FEEDBACK_ITEMS + 1)))
    question = OpenQuestion("q", "question", "test", OpenQuestionStatus.OPEN, None)
    with pytest.raises(ValueError, match="open_questions"):
        replace(result, open_questions=(question,) * (MAX_FEEDBACK_ITEMS + 1))
    with pytest.raises(ValueError, match="next_actions"):
        replace(result, next_actions=(_action(status=IterationActionStatus.COMPLETED),))


@pytest.mark.parametrize(
    ("action", "match"),
    [
        (_action(status=IterationActionStatus.PROPOSED), "APPROVED"),
        (_action(status=IterationActionStatus.REJECTED), "pending_actions"),
        (_action(action_type=IterationActionType.RUN_AGENT), "ANALYZE_EXECUTION_OUTPUT"),
        (_action(metadata={}), "source_index"),
        (_action(metadata={"source_index": "0"}), "int"),
        (_action(metadata={"source_index": True}), "int"),
        (_action(metadata={"source_index": -1}), "0以上"),
    ],
)
def test_action_validation_rejects_invalid_action(action, match):
    with pytest.raises(ValueError, match=match):
        _apply(_session(action))


def test_validation_rejects_missing_mismatched_inactive_and_old_time():
    session = _session()
    with pytest.raises(ValueError, match="1件"):
        _apply(session, action_id="missing")
    with pytest.raises(ValueError, match="一致"):
        _apply(session, source_index=1)
    stopped = IterationStateManager().stop_session(
        session, IterationStopReason.USER_STOPPED, NOW + timedelta(minutes=2)
    )
    with pytest.raises(ValueError, match="ACTIVE"):
        _apply(stopped, minute=3)
    with pytest.raises(ValueError, match="過去"):
        _apply(session, minute=0)


@pytest.mark.parametrize(
    "analysis",
    [
        _analysis(),
        _analysis(status=ExecutionStatus.FAILED, exit_code=1, successful=False),
        _analysis(
            status=ExecutionStatus.TIMED_OUT,
            exit_code=None,
            timed_out=True,
            successful=False,
        ),
        _analysis(truncated=True),
    ],
)
def test_started_execution_is_completed_feedback_and_preserves_structured_state(analysis):
    result = _apply(analysis=analysis)
    feedback = result.feedback_result
    assert feedback.status is ExecutionFeedbackStatus.COMPLETED
    assert feedback.execution_analysis is analysis
    assert result.step.execution_result is analysis
    assert analysis.execution.status.value in feedback.summary
    assert f"exit_code={analysis.execution.exit_code}" in feedback.summary
    assert f"timed_out={analysis.execution.timed_out}" in feedback.summary
    assert f"output_truncated={analysis.execution.output_truncated}" in feedback.summary
    assert f"successful_execution={analysis.successful_execution}" in feedback.summary
    assert result.step.status is IterationStepStatus.COMPLETED


def test_not_started_analysis_is_failed_feedback_and_action_finalized():
    analysis = _analysis(
        status=ExecutionStatus.REJECTED,
        started=False,
        exit_code=None,
        successful=False,
    )
    result = _apply(analysis=analysis)
    assert result.feedback_result.status is ExecutionFeedbackStatus.FAILED
    assert result.step.status is IterationStepStatus.FAILED
    assert result.step.completed_action_ids == ()
    assert result.step.error_message == "Python実行が開始されていません。"
    assert result.session.pending_actions == ()
    assert result.session.status is IterationSessionStatus.ACTIVE


def test_flags_are_exactly_deduplicated_ordered_and_merged_without_stopping():
    analysis = _analysis(flags=("FLAG{same}", "FLAG{same}", "flag{same}"))
    original = _session()
    action = original.pending_actions[0]
    result = _apply(original, analysis)
    assert result.feedback_result.flag_candidates == ("FLAG{same}", "flag{same}")
    assert analysis.primary_flag == "FLAG{same}"
    assert result.session.flag_candidates == ("FLAG{same}", "flag{same}")
    assert result.session.primary_flag == "FLAG{same}"
    assert result.session.status is IterationSessionStatus.ACTIVE
    assert result.session.stop_reason is None
    assert original.pending_actions == (action,)
    assert action.status is IterationActionStatus.APPROVED
    assert analysis.flag_candidates[0].flag == "FLAG{same}"


def test_open_questions_are_deterministic_and_do_not_include_output_text():
    stdout = "secret stdout body"
    stderr = "secret stderr body"
    analysis = _analysis(
        status=ExecutionStatus.FAILED,
        exit_code=2,
        timed_out=True,
        truncated=True,
        stdout=stdout,
        stderr=stderr,
        successful=False,
    )
    result = _apply(analysis=analysis)
    questions = result.feedback_result.open_questions
    assert tuple(question.question_id for question in questions) == (
        "execution:0:failure",
        "execution:0:timeout",
        "execution:0:truncated",
    )
    text = " ".join(question.question for question in questions)
    assert stdout not in text and stderr not in text
    assert all(question.status is OpenQuestionStatus.OPEN for question in questions)
    assert result.session.open_questions == questions


def test_success_has_no_unnecessary_open_question():
    result = _apply(analysis=_analysis())
    assert result.feedback_result.open_questions == ()
    assert result.step.open_questions == ()


def test_same_source_index_is_repeated_and_different_index_is_independent():
    analysis = _analysis(flags=("FLAG{candidate}",))
    first = _apply(analysis=analysis)
    second_session = _add_action(first.session, _action("feedback-again"), 3)
    repeated = _apply(
        second_session,
        analysis,
        action_id="feedback-again",
        minute=4,
    )
    assert repeated.feedback_result.status is ExecutionFeedbackStatus.REPEATED
    assert repeated.feedback_result.repeated
    assert repeated.step.status is IterationStepStatus.SKIPPED
    assert repeated.step.completed_action_ids == ("feedback-again",)
    assert repeated.step.feedback_source_index == 0
    assert repeated.session.pending_actions == ()
    assert repeated.session.status is IterationSessionStatus.ACTIVE

    other_action = _action("feedback-1", metadata={"source_index": 1})
    other_session = _add_action(first.session, other_action, 3)
    other = _apply(
        other_session,
        analysis,
        source_index=1,
        action_id="feedback-1",
        minute=4,
    )
    assert other.feedback_result.status is ExecutionFeedbackStatus.COMPLETED
    assert not other.feedback_result.repeated


def test_step_shape_action_finalization_and_input_immutability():
    session = _session()
    action = session.pending_actions[0]
    analysis = _analysis()
    result = _apply(session, analysis)
    assert isinstance(result, ExecutionFeedbackExecutionResult)
    assert result.step.iteration_number == 2
    assert result.session.steps[-1] is result.step
    assert result.step.agent_result is None
    assert result.step.execution_result is analysis
    assert result.step.hypotheses == ()
    assert result.step.proposed_actions == ()
    assert result.step.completed_action_ids == (action.action_id,)
    assert result.step.error_message is None
    assert result.step.feedback_source_index == 0
    assert result.session.pending_actions == ()
    assert session.current_iteration == 1
    assert session.pending_actions == (action,)
    assert action.status is IterationActionStatus.APPROVED
    assert analysis.execution.stdout == "ordinary stdout"
    with pytest.raises(ValueError, match="1件"):
        _apply(result.session, analysis, minute=3)


def test_iteration_step_feedback_index_is_optional_and_validated():
    existing = _session().steps[0]
    assert existing.feedback_source_index is None
    with pytest.raises(ValueError, match="feedback_source_index"):
        replace(existing, feedback_source_index=-1)


def test_feedback_scope_has_no_execution_analysis_ai_agent_or_event_operations():
    modules = (
        "app.iteration.execution_feedback_result",
        "app.iteration.execution_feedback_coordinator",
    )
    source = "\n".join(
        inspect.getsource(__import__(module, fromlist=["*"])) for module in modules
    ).casefold()
    for forbidden in (
        "pythonexecutionrunner", "executionresultanalyzer", "flagextractor",
        "subprocess", "openai", "aiclient", "agentrouter", "agentcoordinator",
        "iterationactionplanner", "iterationstopevaluator", "eventpublisher",
        "controller", "challengeservice", "datetime.now", "time.", "input(",
        "\nprint(", "\nopen(", "write_text", "write_bytes",
    ):
        assert forbidden not in source
