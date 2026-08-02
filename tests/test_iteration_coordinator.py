import inspect
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import pytest

from app.iteration.iteration_action import (
    IterationAction,
    IterationActionStatus,
    IterationActionType,
)
from app.iteration.iteration_coordinator import (
    IterationCoordinator,
    IterationExecutionResult,
)
from app.iteration.iteration_state import (
    AnalysisHypothesis,
    HypothesisStatus,
    IterationSessionStatus,
    IterationStep,
    IterationStepStatus,
    IterationStopReason,
)
from app.iteration.iteration_state_manager import IterationStateManager
from app.iteration.local_analysis_executor import (
    BaseLocalAnalysisExecutor,
    HypothesisReviewExecutor,
    LocalAnalysisRequest,
)
from app.iteration.local_analysis_result import (
    MAX_LOCAL_RESULT_ITEMS,
    LocalAnalysisResult,
    LocalAnalysisStatus,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(minutes=1)


def _hypothesis(status=HypothesisStatus.OPEN):
    return AnalysisHypothesis(
        "hyp-001",
        "curl and execute are untrusted words, not commands",
        "test",
        80,
        status,
        ("existing evidence",),
    )


def _action(
    status=IterationActionStatus.PROPOSED,
    action_type=IterationActionType.RUN_LOCAL_ANALYSIS,
    metadata=None,
    identifier="hypothesis:hyp-001",
):
    return IterationAction(
        identifier,
        action_type,
        status,
        "Review hypothesis",
        "Review structured evidence",
        75,
        "High-confidence hypothesis",
        None,
        False,
        metadata
        if metadata is not None
        else {"analysis_type": "hypothesis_review", "hypothesis_id": "hyp-001"},
    )


def _step(action, hypothesis=None):
    return IterationStep(
        1,
        IterationStepStatus.COMPLETED,
        "initial",
        None,
        None,
        (hypothesis,) if hypothesis is not None else (),
        (),
        (action,),
        (),
        None,
    )


def _session(
    *,
    hypothesis=None,
    action=None,
    approve=True,
):
    manager = IterationStateManager()
    action = action or _action()
    session = manager.create_session("session", NOW)
    session = manager.append_step(session, _step(action, hypothesis or _hypothesis()), LATER)
    if approve:
        session = manager.decide_action(session, action.action_id, True, LATER)
    return session


def _result(status=LocalAnalysisStatus.COMPLETED, **values):
    arguments = {
        "action_id": "hypothesis:hyp-001",
        "analysis_type": "hypothesis_review",
        "status": status,
        "summary": "local summary",
        "hypotheses": (_hypothesis(),) if status is LocalAnalysisStatus.COMPLETED else (),
        "open_questions": (),
        "flag_candidates": (),
        "next_actions": (),
        "error_message": "failed" if status is LocalAnalysisStatus.FAILED else None,
    }
    arguments.update(values)
    return LocalAnalysisResult(**arguments)


class RecordingExecutor(BaseLocalAnalysisExecutor):
    def __init__(self, result=None, error=None, analysis_type="hypothesis_review"):
        self._analysis_type = analysis_type
        self.result = result or _result()
        self.error = error
        self.requests = []

    @property
    def analysis_type(self):
        return self._analysis_type

    def execute(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result


def _coordinator(executor=None, manager=None):
    executor = executor or HypothesisReviewExecutor()
    manager = manager or IterationStateManager()
    return IterationCoordinator(state_manager=manager, executors=(executor,))


def test_executor_contract_request_and_result_dtos_are_frozen_slotted():
    assert inspect.isabstract(BaseLocalAnalysisExecutor)
    executor = HypothesisReviewExecutor()
    request = LocalAnalysisRequest(_session(), _action(IterationActionStatus.APPROVED))
    result = executor.execute(request)
    assert executor.analysis_type == "hypothesis_review"
    assert isinstance(result, LocalAnalysisResult)
    for value in (request, result):
        assert not hasattr(value, "__dict__")
        with pytest.raises(FrozenInstanceError):
            value.__setattr__(next(iter(value.__slots__)), None)


def test_local_result_validates_text_collection_and_proposed_action_limits():
    with pytest.raises(ValueError, match="summary"):
        replace(_result(), summary="x" * 501)
    with pytest.raises(ValueError, match="error_message"):
        replace(_result(), error_message="x" * 501)
    with pytest.raises(ValueError, match="hypotheses"):
        replace(_result(), hypotheses=tuple(_hypothesis() for _ in range(MAX_LOCAL_RESULT_ITEMS + 1)))
    with pytest.raises(ValueError, match="next_actions"):
        replace(
            _result(),
            next_actions=tuple(_action() for _ in range(MAX_LOCAL_RESULT_ITEMS + 1)),
        )
    with pytest.raises(ValueError, match="PROPOSED"):
        replace(_result(), next_actions=(_action(IterationActionStatus.APPROVED),))


def test_duplicate_executor_analysis_type_is_rejected_and_order_is_preserved():
    first = RecordingExecutor()
    second = RecordingExecutor(analysis_type="other")
    coordinator = IterationCoordinator(
        state_manager=IterationStateManager(), executors=(first, second)
    )
    assert coordinator.executors == (first, second)
    with pytest.raises(ValueError, match="重複"):
        IterationCoordinator(
            state_manager=IterationStateManager(),
            executors=(first, RecordingExecutor()),
        )


@pytest.mark.parametrize("status", [HypothesisStatus.OPEN, HypothesisStatus.SUPPORTED])
def test_hypothesis_review_completes_open_or_supported_without_invention(status):
    hypothesis = _hypothesis(status)
    request = LocalAnalysisRequest(_session(hypothesis=hypothesis), _action())
    result = HypothesisReviewExecutor().execute(request)
    assert result.status is LocalAnalysisStatus.COMPLETED
    assert result.hypotheses == (hypothesis,)
    assert result.hypotheses[0] is hypothesis
    assert result.flag_candidates == () and result.next_actions == ()
    assert "hyp-001" in result.summary
    assert hypothesis.statement not in result.summary


@pytest.mark.parametrize("status", [HypothesisStatus.RESOLVED, HypothesisStatus.REJECTED])
def test_hypothesis_review_skips_terminal_hypothesis(status):
    result = HypothesisReviewExecutor().execute(
        LocalAnalysisRequest(_session(hypothesis=_hypothesis(status)), _action())
    )
    assert result.status is LocalAnalysisStatus.SKIPPED
    assert result.hypotheses == ()
    assert result.flag_candidates == () and result.next_actions == ()


def test_hypothesis_review_fails_for_missing_id_or_hypothesis():
    missing_id = HypothesisReviewExecutor().execute(
        LocalAnalysisRequest(_session(), _action(metadata={"analysis_type": "hypothesis_review"}))
    )
    assert missing_id.status is LocalAnalysisStatus.FAILED
    unknown = HypothesisReviewExecutor().execute(
        LocalAnalysisRequest(
            _session(),
            _action(
                metadata={
                    "analysis_type": "hypothesis_review",
                    "hypothesis_id": "unknown",
                }
            ),
        )
    )
    assert unknown.status is LocalAnalysisStatus.FAILED


@pytest.mark.parametrize(
    ("action", "match"),
    [
        (_action(), "APPROVED"),
        (_action(IterationActionStatus.REJECTED), "1件"),
        (
            _action(
                IterationActionStatus.APPROVED,
                IterationActionType.MANUAL_REVIEW,
            ),
            "RUN_LOCAL_ANALYSIS",
        ),
        (
            _action(IterationActionStatus.APPROVED, metadata={"hypothesis_id": "hyp-001"}),
            "analysis_type",
        ),
        (
            _action(
                IterationActionStatus.APPROVED,
                metadata={"analysis_type": "unknown", "hypothesis_id": "hyp-001"},
            ),
            "登録されていません",
        ),
    ],
)
def test_action_validation_rejects_unapproved_wrong_type_or_executor(action, match):
    session = _session(action=action, approve=False)
    with pytest.raises(ValueError, match=match):
        _coordinator().execute_action(
            session=session,
            action_id=action.action_id,
            updated_at=LATER,
        )


def test_action_validation_rejects_missing_id_inactive_and_old_time():
    session = _session()
    with pytest.raises(ValueError, match="1件"):
        _coordinator().execute_action(session=session, action_id="missing", updated_at=LATER)
    stopped = IterationStateManager().stop_session(
        session, IterationStopReason.USER_STOPPED, LATER
    )
    with pytest.raises(ValueError, match="ACTIVE"):
        _coordinator().execute_action(
            session=stopped,
            action_id="hypothesis:hyp-001",
            updated_at=LATER,
        )
    with pytest.raises(ValueError, match="過去"):
        _coordinator().execute_action(
            session=session,
            action_id="hypothesis:hyp-001",
            updated_at=NOW,
        )


@pytest.mark.parametrize(
    ("local_status", "step_status", "final_status"),
    [
        (
            LocalAnalysisStatus.COMPLETED,
            IterationStepStatus.COMPLETED,
            IterationActionStatus.COMPLETED,
        ),
        (
            LocalAnalysisStatus.SKIPPED,
            IterationStepStatus.SKIPPED,
            IterationActionStatus.SKIPPED,
        ),
        (
            LocalAnalysisStatus.FAILED,
            IterationStepStatus.FAILED,
            IterationActionStatus.FAILED,
        ),
    ],
)
def test_coordinator_executes_once_builds_step_and_finalizes_action(
    local_status,
    step_status,
    final_status,
):
    executor = RecordingExecutor(_result(local_status))
    session = _session()
    original_action = session.pending_actions[0]
    result = _coordinator(executor).execute_action(
        session=session,
        action_id=original_action.action_id,
        updated_at=LATER + timedelta(minutes=1),
    )
    assert isinstance(result, IterationExecutionResult)
    assert len(executor.requests) == 1
    assert executor.requests[0].session is session
    assert executor.requests[0].action is original_action
    assert result.step.iteration_number == 2
    assert result.step.status is step_status
    assert result.step.summary == result.local_result.summary
    assert result.step.agent_result is result.step.execution_result is None
    assert result.step.hypotheses == result.local_result.hypotheses
    assert result.step.open_questions == result.local_result.open_questions
    assert result.step.proposed_actions == result.local_result.next_actions
    expected_ids = () if final_status is IterationActionStatus.FAILED else (original_action.action_id,)
    assert result.step.completed_action_ids == expected_ids
    assert result.session.steps[-1] is result.step
    assert result.session.current_iteration == 2
    assert result.session.pending_actions == ()
    assert result.session.status is IterationSessionStatus.ACTIVE
    assert result.session.updated_at == LATER + timedelta(minutes=1)
    assert session.current_iteration == 1
    assert session.pending_actions == (original_action,)
    assert original_action.status is IterationActionStatus.APPROVED


def test_executor_next_actions_are_preserved_as_proposed_pending_actions():
    next_action = _action(identifier="next", metadata={"safe": "value"})
    executor = RecordingExecutor(_result(next_actions=(next_action,)))
    result = _coordinator(executor).execute_action(
        session=_session(),
        action_id="hypothesis:hyp-001",
        updated_at=LATER + timedelta(minutes=1),
    )
    assert result.step.proposed_actions == (next_action,)
    assert result.session.pending_actions == (next_action,)


def test_executor_exception_becomes_limited_failed_history_without_session_failure():
    message = "x" * 600
    executor = RecordingExecutor(error=RuntimeError(message))
    result = _coordinator(executor).execute_action(
        session=_session(),
        action_id="hypothesis:hyp-001",
        updated_at=LATER + timedelta(minutes=1),
    )
    assert result.local_result.status is LocalAnalysisStatus.FAILED
    assert result.step.status is IterationStepStatus.FAILED
    assert result.local_result.error_message.startswith("RuntimeError:")
    assert len(result.local_result.error_message) <= 500
    assert result.step.error_message == result.local_result.error_message
    assert result.session.status is IterationSessionStatus.ACTIVE
    assert result.session.pending_actions == ()


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit()])
def test_base_exceptions_are_not_caught(error):
    executor = RecordingExecutor(error=error)
    with pytest.raises(type(error)):
        _coordinator(executor).execute_action(
            session=_session(),
            action_id="hypothesis:hyp-001",
            updated_at=LATER + timedelta(minutes=1),
        )


def test_completed_action_cannot_be_executed_again():
    result = _coordinator().execute_action(
        session=_session(),
        action_id="hypothesis:hyp-001",
        updated_at=LATER + timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match="1件"):
        _coordinator().execute_action(
            session=result.session,
            action_id="hypothesis:hyp-001",
            updated_at=LATER + timedelta(minutes=2),
        )


def test_state_manager_complete_action_requires_approved_and_terminal_status():
    manager = IterationStateManager()
    proposed = _session(approve=False)
    with pytest.raises(ValueError, match="APPROVED"):
        manager.complete_action(
            proposed,
            "hypothesis:hyp-001",
            IterationActionStatus.COMPLETED,
            LATER,
        )
    approved = _session()
    with pytest.raises(ValueError, match="最終状態"):
        manager.complete_action(
            approved,
            "hypothesis:hyp-001",
            IterationActionStatus.APPROVED,
            LATER,
        )


def test_iteration_coordinator_has_no_out_of_scope_dependencies_or_operations():
    modules = (
        "app.iteration.local_analysis_executor",
        "app.iteration.local_analysis_result",
        "app.iteration.iteration_coordinator",
    )
    source = "\n".join(
        inspect.getsource(__import__(module, fromlist=["*"])) for module in modules
    ).casefold()
    for forbidden in (
        "subprocess", "openai", "aiclient", "agentrouter", "agentcoordinator",
        "iterationactionplanner", "iterationstopevaluator", "eventpublisher",
        "controller", "challengeservice", "datetime.now", "time.", "input(",
        "print(", "open(", "write_text", "write_bytes",
    ):
        assert forbidden not in source
