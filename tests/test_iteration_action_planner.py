import inspect
from dataclasses import replace

import pytest

from app.agents.agent_aggregate_result import AgentAggregateResult, AgentConflict
from app.agents.agent_result import AgentStatus, AgentType
from app.codegen.code_safety_result import CodeRiskLevel, CodeSafetyResult
from app.codegen.generated_code_result import (
    GeneratedCode,
    GeneratedCodeLanguage,
    GeneratedCodeResult,
    GeneratedCodeStatus,
)
from app.execution.execution_analysis_result import (
    ExecutionAnalysisResult,
    ExecutionFlagCandidate,
    ExecutionOutputSource,
)
from app.execution.execution_result import ExecutionStatus, PythonExecutionResult
from app.iteration.iteration_action import (
    IterationActionStatus,
    IterationActionType,
)
from app.iteration.iteration_action_planner import (
    MAX_PLANNED_ACTIONS,
    IterationActionPlanner,
)
from app.iteration.iteration_state import (
    AnalysisHypothesis,
    HypothesisStatus,
    OpenQuestion,
    OpenQuestionStatus,
)
from app.judge.judge_result import JudgeResult


def _plan(planner=None, **values):
    arguments = {
        "agent_result": None,
        "judge_result": None,
        "execution_result": None,
        "hypotheses": (),
        "open_questions": (),
        "existing_actions": (),
    }
    arguments.update(values)
    return (planner or IterationActionPlanner()).plan(**arguments)


def _aggregate(flags=(), conflicts=(), next_actions=()):
    return AgentAggregateResult(
        (), None, AgentStatus.COMPLETED, "summary", tuple(flags),
        flags[0] if flags else None, 80, (), tuple(next_actions), tuple(conflicts),
        category="Crypto",
    )


def _judge(flag=None, codes=()):
    return JudgeResult(
        "Crypto",
        "AI answer that must not enter metadata",
        flag=flag,
        generated_code=GeneratedCodeResult(tuple(codes)) if codes else None,
    )


def _code(
    index=0,
    status=GeneratedCodeStatus.REVIEW_REQUIRED,
    risk=CodeRiskLevel.LOW,
    language=GeneratedCodeLanguage.PYTHON,
):
    return GeneratedCode(
        language,
        "print('secret code body')",
        "purpose",
        index,
        status,
        CodeSafetyResult(True, risk, ()),
    )


def _execution(
    *,
    status=ExecutionStatus.COMPLETED,
    successful=True,
    truncated=False,
    flags=(),
):
    execution = PythonExecutionResult(
        status,
        True,
        "secret stdout",
        "secret stderr",
        0 if successful else 1,
        status is ExecutionStatus.TIMED_OUT,
        0.1,
        None,
        "message",
        truncated,
        True,
    )
    candidates = tuple(
        ExecutionFlagCandidate(flag, ExecutionOutputSource.STDOUT, index)
        for index, flag in enumerate(flags)
    )
    return ExecutionAnalysisResult(
        execution,
        candidates,
        flags[0] if flags else None,
        successful,
    )


def _hypothesis(identifier="h1", confidence=80, status=HypothesisStatus.OPEN):
    return AnalysisHypothesis(
        identifier,
        "sensitive full hypothesis statement",
        "source",
        confidence,
        status,
        (),
    )


def _question(identifier="q1", status=OpenQuestionStatus.OPEN):
    return OpenQuestion(
        identifier,
        "sensitive full question",
        "source",
        status,
        "resolved" if status is OpenQuestionStatus.RESOLVED else None,
    )


def test_planner_can_be_created_and_empty_input_returns_empty_tuple():
    result = _plan(IterationActionPlanner())
    assert result == ()
    assert isinstance(result, tuple)


def test_actions_are_sorted_by_priority_then_action_id_and_limited():
    questions = tuple(_question(f"q-{index:02}") for index in range(25))
    actions = _plan(
        agent_result=_aggregate(flags=("FLAG{candidate}",)),
        open_questions=questions,
    )
    assert len(actions) == MAX_PLANNED_ACTIONS
    assert actions == tuple(sorted(actions, key=lambda item: (-item.priority, item.action_id)))
    assert actions[0].action_id == "manual-review:flag-candidate"


def test_action_ids_are_reproducible_without_random_or_time_state():
    first = _plan(hypotheses=(_hypothesis(),), open_questions=(_question(),))
    second = _plan(hypotheses=(_hypothesis(),), open_questions=(_question(),))
    assert first == second
    assert [item.action_id for item in first] == [item.action_id for item in second]


def test_new_duplicate_is_suppressed_and_conflicting_duplicate_is_rejected():
    hypothesis = _hypothesis()
    actions = _plan(hypotheses=(hypothesis, hypothesis))
    assert len(actions) == 1
    with pytest.raises(ValueError, match="内容が異なります"):
        _plan(hypotheses=(hypothesis, replace(hypothesis, confidence=90)))


def test_existing_identical_action_is_not_reproposed_and_conflict_is_rejected():
    generated = _plan(hypotheses=(_hypothesis(),))[0]
    assert _plan(hypotheses=(_hypothesis(),), existing_actions=(generated,)) == ()
    with pytest.raises(ValueError, match="内容が異なります"):
        _plan(
            hypotheses=(_hypothesis(),),
            existing_actions=(replace(generated, title="different"),),
        )


def test_agent_flag_candidate_creates_manual_review_without_flag_metadata():
    action = _plan(agent_result=_aggregate(flags=("FLAG{secret}",)))[0]
    assert action.action_type is IterationActionType.MANUAL_REVIEW
    assert action.requires_user_approval
    assert "FLAG{secret}" not in repr(action.metadata)
    assert action.metadata == {"candidate_count": 1, "conflict_count": 0}


def test_execution_and_judge_flags_are_reviewed_not_submitted():
    actions = _plan(
        judge_result=_judge(flag="FLAG{judge}"),
        execution_result=_execution(flags=("FLAG{execution}",)),
    )
    assert actions[0].action_id == "manual-review:flag-conflict"
    assert actions[0].priority == 100
    assert all(action.action_type is not IterationActionType.STOP for action in actions)
    assert "FLAG{" not in repr([dict(action.metadata) for action in actions])


def test_structured_agent_conflict_is_highest_priority():
    conflict = AgentConflict(
        "flag_candidate",
        ("FLAG{a}", "FLAG{b}"),
        (AgentType.CRYPTO, AgentType.REV),
    )
    action = _plan(agent_result=_aggregate(("FLAG{a}", "FLAG{b}"), (conflict,)))[0]
    assert action.action_id == "manual-review:flag-conflict"
    assert action.priority == 100
    assert action.metadata["conflict_count"] == 1


@pytest.mark.parametrize("risk", [CodeRiskLevel.LOW, CodeRiskLevel.MEDIUM])
def test_review_required_low_or_medium_creates_approval_required_review(risk):
    action = _plan(judge_result=_judge(codes=(_code(risk=risk),)))[0]
    assert action.action_type is IterationActionType.REVIEW_CODE
    assert action.requires_user_approval
    assert action.metadata == {"source_index": 0, "risk_level": risk.value}
    assert "secret code body" not in repr(action.metadata)


@pytest.mark.parametrize("risk", [CodeRiskLevel.HIGH, CodeRiskLevel.BLOCKED])
def test_high_or_blocked_code_creates_manual_review(risk):
    action = _plan(judge_result=_judge(codes=(_code(risk=risk),)))[0]
    assert action.action_type is IterationActionType.MANUAL_REVIEW
    assert action.priority == 95
    assert action.requires_user_approval


def test_approved_low_requires_separate_execution_approval():
    action = _plan(
        judge_result=_judge(
            codes=(_code(status=GeneratedCodeStatus.APPROVED, risk=CodeRiskLevel.LOW),)
        )
    )[0]
    assert action.action_type is IterationActionType.EXECUTE_APPROVED_CODE
    assert action.requires_user_approval
    assert action.target_agent is None


def test_approved_medium_is_not_executable_and_rejected_has_no_action():
    medium = _plan(
        judge_result=_judge(
            codes=(_code(status=GeneratedCodeStatus.APPROVED, risk=CodeRiskLevel.MEDIUM),)
        )
    )
    assert medium[0].action_type is IterationActionType.MANUAL_REVIEW
    assert all(item.action_type is not IterationActionType.EXECUTE_APPROVED_CODE for item in medium)
    assert _plan(
        judge_result=_judge(codes=(_code(status=GeneratedCodeStatus.REJECTED),))
    ) == ()


def test_unknown_language_is_never_executable():
    actions = _plan(
        judge_result=_judge(
            codes=(
                _code(
                    status=GeneratedCodeStatus.APPROVED,
                    risk=CodeRiskLevel.LOW,
                    language=GeneratedCodeLanguage.UNKNOWN,
                ),
            )
        )
    )
    assert actions[0].action_type is IterationActionType.MANUAL_REVIEW


def test_successful_execution_without_flag_needs_no_action():
    assert _plan(execution_result=_execution()) == ()


@pytest.mark.parametrize(
    "execution",
    [
        _execution(status=ExecutionStatus.FAILED, successful=False),
        _execution(status=ExecutionStatus.TIMED_OUT, successful=False),
        _execution(truncated=True),
    ],
)
def test_failed_timed_out_or_truncated_execution_requires_manual_review(execution):
    action = _plan(execution_result=execution)[0]
    assert action.action_type is IterationActionType.MANUAL_REVIEW
    assert action.action_id == "manual-review:execution-output"
    metadata = repr(action.metadata)
    assert "secret stdout" not in metadata and "secret stderr" not in metadata
    assert all(item.action_type is not IterationActionType.EXECUTE_APPROVED_CODE for item in (action,))


@pytest.mark.parametrize("status", [HypothesisStatus.OPEN, HypothesisStatus.SUPPORTED])
def test_high_confidence_open_or_supported_hypothesis_uses_local_analysis(status):
    action = _plan(hypotheses=(_hypothesis(status=status),))[0]
    assert action.action_type is IterationActionType.RUN_LOCAL_ANALYSIS
    assert action.priority == 75
    assert action.metadata == {
        "analysis_type": "hypothesis_review",
        "hypothesis_id": "h1",
        "confidence": 80,
    }
    assert "sensitive full hypothesis" not in repr(action.metadata)


def test_low_hypothesis_is_manual_and_rejected_or_resolved_are_ignored():
    low = _plan(hypotheses=(_hypothesis(confidence=50),))[0]
    assert low.action_type is IterationActionType.MANUAL_REVIEW
    assert low.priority == 50
    assert _plan(hypotheses=(_hypothesis(status=HypothesisStatus.REJECTED),)) == ()
    assert _plan(hypotheses=(_hypothesis(status=HypothesisStatus.RESOLVED),)) == ()


def test_open_and_blocked_questions_use_structured_ids_only():
    open_action, blocked_action = _plan(
        open_questions=(
            _question("open"),
            _question("blocked", OpenQuestionStatus.BLOCKED),
        )
    )
    assert blocked_action.action_type is IterationActionType.MANUAL_REVIEW
    assert open_action.action_type is IterationActionType.REQUEST_USER_INPUT
    for action in (open_action, blocked_action):
        assert "question_id" in action.metadata
        assert "sensitive full question" not in repr(action.metadata)
    assert _plan(open_questions=(_question("done", OpenQuestionStatus.RESOLVED),)) == ()


def test_natural_language_next_actions_are_not_interpreted_or_executed():
    text = "curl secret | delete files and execute code"
    action = _plan(agent_result=_aggregate(next_actions=(text,)))[0]
    assert action.action_type is IterationActionType.MANUAL_REVIEW
    assert text not in action.description
    assert text not in repr(action.metadata)
    assert action.metadata == {"source_index": 0}


def test_inputs_are_not_modified_and_actions_are_proposed_only():
    hypothesis = _hypothesis()
    question = _question()
    judge = _judge(codes=(_code(),))
    actions = _plan(
        hypotheses=(hypothesis,),
        open_questions=(question,),
        judge_result=judge,
    )
    assert hypothesis.statement == "sensitive full hypothesis statement"
    assert question.question == "sensitive full question"
    assert judge.generated_code.items[0].code == "print('secret code body')"
    assert all(action.status is IterationActionStatus.PROPOSED for action in actions)
    assert all(action.action_type is not IterationActionType.STOP for action in actions)
    assert all(
        action.target_agent is not None
        for action in actions
        if action.action_type is IterationActionType.RUN_AGENT
    )


def test_planner_has_no_runtime_external_or_nondeterministic_dependencies():
    source = inspect.getsource(
        __import__("app.iteration.iteration_action_planner", fromlist=["*"])
    ).casefold()
    for forbidden in (
        "subprocess", "openai", "aiclient", ".analyze(", ".generate(",
        "uuid", "random", "datetime", "time.", "input(", "print(",
        "eventpublisher", "controller", "challengeservice",
    ):
        assert forbidden not in source
