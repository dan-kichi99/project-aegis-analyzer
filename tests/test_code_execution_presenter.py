from dataclasses import FrozenInstanceError

import pytest

from app.codegen.code_safety_result import (
    CodeRiskCategory,
    CodeRiskLevel,
    CodeSafetyFinding,
    CodeSafetyResult,
)
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
from app.presentation import (
    CodeApprovalDecision,
    CodeApprovalRequest,
    CodeExecutionPresenter,
    CodeExecutionRequest,
)


def _safety(risk=CodeRiskLevel.LOW, parseable=True, findings=()):
    return CodeSafetyResult(parseable, risk, findings)


def _code(risk=CodeRiskLevel.LOW, **changes):
    values = {
        "language": GeneratedCodeLanguage.PYTHON,
        "code": "print('original')",
        "purpose": "Flag候補を調べる",
        "source_index": 0,
        "status": GeneratedCodeStatus.REVIEW_REQUIRED,
        "safety": _safety(risk),
    }
    values.update(changes)
    return GeneratedCode(**values)


def _analysis(**changes):
    values = {
        "status": ExecutionStatus.COMPLETED,
        "started": True,
        "stdout": "FLAG{candidate}",
        "stderr": "warning",
        "exit_code": 0,
        "timed_out": False,
        "duration_seconds": 0.2,
        "failure_reason": None,
        "message": "done",
        "output_truncated": False,
        "cleanup_succeeded": True,
    }
    values.update(changes)
    execution = PythonExecutionResult(**values)
    candidate = ExecutionFlagCandidate(
        "FLAG{candidate}", ExecutionOutputSource.STDOUT, 0
    )
    return ExecutionAnalysisResult(execution, (candidate,), candidate.flag, values["exit_code"] == 0 and not values["timed_out"])


def test_request_dtos_are_frozen_slotted_and_validate_indexes():
    values = (
        CodeApprovalRequest(0, CodeApprovalDecision.APPROVE),
        CodeExecutionRequest(0),
    )
    for value in values:
        assert not hasattr(value, "__dict__")
        with pytest.raises(FrozenInstanceError):
            value.source_index = 1
    for invalid in (-1,):
        with pytest.raises(ValueError):
            CodeExecutionRequest(invalid)
    with pytest.raises(TypeError):
        CodeExecutionRequest(True)


def test_initial_candidates_preserve_order_source_code_and_purpose():
    presenter = CodeExecutionPresenter()
    first = _code(source_index=2)
    second = _code(source_index=5, purpose=None, code="print(2)")
    initial = presenter.initial_state()
    state = presenter.present_candidates(GeneratedCodeResult((first, second)))
    assert initial.candidates == () and initial.selected_candidate is None
    assert [item.source_index for item in state.candidates] == [2, 5]
    assert state.candidates[0].code == first.code
    assert state.candidates[0].purpose == first.purpose
    assert state.candidates[1].code == "print(2)"
    assert first.status is GeneratedCodeStatus.REVIEW_REQUIRED


def test_safety_findings_and_syntax_error_are_converted_in_order():
    findings = (
        CodeSafetyFinding(CodeRiskCategory.SYNTAX, CodeRiskLevel.BLOCKED, "invalid syntax", 3, None),
        CodeSafetyFinding(CodeRiskCategory.PROCESS, CodeRiskLevel.HIGH, "process use", 4, "subprocess.Popen"),
    )
    state = CodeExecutionPresenter().present_candidates(
        GeneratedCodeResult((_code(CodeRiskLevel.BLOCKED, safety=_safety(CodeRiskLevel.BLOCKED, False, findings)),))
    )
    candidate = state.candidates[0]
    assert candidate.risk_level == "blocked" and not candidate.parseable
    assert candidate.syntax_error == "invalid syntax"
    assert "syntax" in candidate.findings[0]
    assert "subprocess.Popen" in candidate.findings[1]


def test_candidate_limits_selection_clear_and_state_immutability():
    presenter = CodeExecutionPresenter()
    with pytest.raises(ValueError):
        presenter.present_candidates(GeneratedCodeResult(tuple(_code(source_index=i) for i in range(6))))
    state = presenter.present_candidates(GeneratedCodeResult((_code(),)))
    selected = presenter.select_candidate(state, 0)
    assert state.selected_candidate is None
    assert selected.selected_candidate is selected.candidates[0]
    assert presenter.select_candidate(selected, None).selected_candidate is None
    for index in (True, -1, 1):
        with pytest.raises(ValueError):
            presenter.select_candidate(state, index)


@pytest.mark.parametrize(
    ("risk", "approve", "execute"),
    [
        (CodeRiskLevel.LOW, True, False),
        (CodeRiskLevel.MEDIUM, True, False),
        (CodeRiskLevel.HIGH, False, False),
        (CodeRiskLevel.BLOCKED, False, False),
    ],
)
def test_review_required_risk_permissions(risk, approve, execute):
    candidate = CodeExecutionPresenter().present_candidates(
        GeneratedCodeResult((_code(risk),))
    ).candidates[0]
    assert candidate.can_approve is approve
    assert candidate.can_reject and candidate.can_defer
    assert candidate.can_execute is execute


def test_unknown_rejected_and_approved_execution_permissions():
    presenter = CodeExecutionPresenter()
    values = (
        _code(language=GeneratedCodeLanguage.UNKNOWN),
        _code(status=GeneratedCodeStatus.REJECTED),
        _code(status=GeneratedCodeStatus.APPROVED),
        _code(CodeRiskLevel.MEDIUM, status=GeneratedCodeStatus.APPROVED),
    )
    candidates = presenter.present_candidates(GeneratedCodeResult(values)).candidates
    assert not candidates[0].can_approve
    assert not any((candidates[1].can_approve, candidates[1].can_reject, candidates[1].can_defer, candidates[1].can_execute))
    assert candidates[2].can_execute
    assert not candidates[3].can_execute


@pytest.mark.parametrize("decision", list(CodeApprovalDecision))
def test_approval_requests_do_not_change_candidate(decision):
    presenter = CodeExecutionPresenter()
    state = presenter.present_candidates(GeneratedCodeResult((_code(),)))
    selected = presenter.select_candidate(state, 0)
    request = presenter.build_approval_request(selected, decision)
    assert request == CodeApprovalRequest(0, decision)
    assert selected.selected_candidate.status == "review_required"


def test_invalid_approval_and_execution_requests_are_rejected():
    presenter = CodeExecutionPresenter()
    state = presenter.present_candidates(GeneratedCodeResult((_code(),)))
    with pytest.raises(ValueError):
        presenter.build_approval_request(state, CodeApprovalDecision.APPROVE)
    selected = presenter.select_candidate(state, 0)
    with pytest.raises(ValueError):
        presenter.build_execution_request(selected)
    approved = presenter.select_candidate(
        presenter.present_candidates(GeneratedCodeResult((_code(status=GeneratedCodeStatus.APPROVED),))), 0
    )
    assert presenter.build_execution_request(approved) == CodeExecutionRequest(0)


def test_execution_result_preserves_output_flags_and_fixed_warnings():
    presenter = CodeExecutionPresenter()
    state = presenter.present_candidates(GeneratedCodeResult((_code(source_index=7),)))
    analysis = _analysis(status=ExecutionStatus.TIMED_OUT, timed_out=True, exit_code=None, output_truncated=True)
    updated = presenter.present_execution_results(state, (analysis,))
    item = updated.execution_results[0]
    assert item.source_index == 7
    assert item.stdout == "FLAG{candidate}" and item.stderr == "warning"
    assert item.timed_out and item.output_truncated and item.cleanup_succeeded
    assert item.flag_candidates == ("FLAG{candidate}",)
    assert item.primary_flag == "FLAG{candidate}"
    assert not item.successful_execution
    assert "候補" in item.warning and "途中出力" in item.warning and "省略" in item.warning
    assert state.execution_results == ()


def test_presentation_dtos_are_frozen_and_slotted():
    presenter = CodeExecutionPresenter()
    state = presenter.present_candidates(GeneratedCodeResult((_code(),)))
    execution = presenter.present_execution_results(state, (_analysis(),)).execution_results[0]
    for value in (state, state.candidates[0], execution):
        assert not hasattr(value, "__dict__")
        with pytest.raises(FrozenInstanceError):
            value.__setattr__(next(iter(value.__slots__)), None)
