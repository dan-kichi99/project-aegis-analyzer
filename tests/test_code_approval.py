import inspect
from unittest.mock import MagicMock, patch

import pytest

from app.codegen.cli_code_approval import (
    MAX_APPROVAL_INPUT_ATTEMPTS,
    CliCodeApproval,
)
from app.codegen.code_approval import (
    ApprovalDecision,
    ApprovalFailureReason,
    CodeApprovalService,
)
from app.codegen.code_safety_result import CodeRiskLevel, CodeSafetyResult
from app.codegen.generated_code_result import (
    GeneratedCode,
    GeneratedCodeLanguage,
    GeneratedCodeResult,
    GeneratedCodeStatus,
)
from app.judge.judge_result import JudgeResult
from app.main import main
from app.utils.result_formatter import ResultFormatter


def _safety(
    risk: CodeRiskLevel = CodeRiskLevel.LOW,
    *,
    parseable: bool = True,
) -> CodeSafetyResult:
    return CodeSafetyResult(parseable=parseable, overall_risk=risk, findings=())


def _code(
    risk: CodeRiskLevel = CodeRiskLevel.LOW,
    **changes,
) -> GeneratedCode:
    values = {
        "language": GeneratedCodeLanguage.PYTHON,
        "code": "print('candidate')",
        "purpose": "候補を確認する",
        "source_index": 0,
        "status": GeneratedCodeStatus.REVIEW_REQUIRED,
        "safety": _safety(risk),
    }
    values.update(changes)
    return GeneratedCode(**values)


@pytest.mark.parametrize("risk", [CodeRiskLevel.LOW, CodeRiskLevel.MEDIUM])
def test_low_and_medium_python_candidates_can_be_approved(risk):
    original = _code(risk)

    result = CodeApprovalService().decide(original, ApprovalDecision.APPROVE)

    assert result.accepted is True
    assert result.reason is None
    assert result.code.status is GeneratedCodeStatus.APPROVED


@pytest.mark.parametrize("risk", [CodeRiskLevel.HIGH, CodeRiskLevel.BLOCKED])
def test_high_and_blocked_candidates_cannot_be_approved(risk):
    original = _code(risk)

    result = CodeApprovalService().decide(original, ApprovalDecision.APPROVE)

    assert result.accepted is False
    assert result.reason is ApprovalFailureReason.RISK_TOO_HIGH
    assert result.code is original


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"language": GeneratedCodeLanguage.UNKNOWN}, ApprovalFailureReason.NOT_PYTHON),
        ({"safety": None}, ApprovalFailureReason.NO_SAFETY_RESULT),
        ({"safety": _safety(parseable=False)}, ApprovalFailureReason.UNPARSEABLE),
        ({"code": "  \n"}, ApprovalFailureReason.EMPTY_CODE),
        ({"source_index": -1}, ApprovalFailureReason.INVALID_INDEX),
        ({"status": GeneratedCodeStatus.PROPOSED}, ApprovalFailureReason.NOT_REVIEWABLE),
    ],
)
def test_invalid_candidates_cannot_be_approved(changes, reason):
    result = CodeApprovalService().decide(
        _code(**changes),
        ApprovalDecision.APPROVE,
    )

    assert result.accepted is False
    assert result.reason is reason


@pytest.mark.parametrize(
    "risk",
    [CodeRiskLevel.LOW, CodeRiskLevel.HIGH, CodeRiskLevel.BLOCKED],
)
def test_review_required_candidate_can_always_be_rejected(risk):
    result = CodeApprovalService().decide(_code(risk), ApprovalDecision.REJECT)

    assert result.accepted is True
    assert result.code.status is GeneratedCodeStatus.REJECTED


def test_decision_returns_new_dto_without_changing_original_fields():
    original = _code()

    result = CodeApprovalService().decide(original, ApprovalDecision.APPROVE)

    assert result.code is not original
    assert original.status is GeneratedCodeStatus.REVIEW_REQUIRED
    assert result.code.code == original.code
    assert result.code.safety is original.safety
    assert result.code.purpose == original.purpose
    assert result.code.source_index == original.source_index


@pytest.mark.parametrize(
    ("initial", "decision"),
    [
        (GeneratedCodeStatus.APPROVED, ApprovalDecision.APPROVE),
        (GeneratedCodeStatus.APPROVED, ApprovalDecision.REJECT),
        (GeneratedCodeStatus.REJECTED, ApprovalDecision.APPROVE),
        (GeneratedCodeStatus.REJECTED, ApprovalDecision.REJECT),
    ],
)
def test_decided_candidate_cannot_transition_again(initial, decision):
    original = _code(status=initial)

    result = CodeApprovalService().decide(original, decision)

    assert result.accepted is False
    assert result.reason is ApprovalFailureReason.ALREADY_DECIDED
    assert result.code.status is initial


@pytest.mark.parametrize("answer", ["y", "Y"])
def test_cli_accepts_case_insensitive_explicit_approval(answer):
    outputs = []
    cli = CliCodeApproval(
        CodeApprovalService(),
        input_fn=MagicMock(return_value=answer),
        output_fn=outputs.append,
    )

    result = cli.review(GeneratedCodeResult((_code(),)))

    assert result.items[0].status is GeneratedCodeStatus.APPROVED
    assert any("未実行" in output for output in outputs)


def test_cli_n_rejects_candidate():
    cli = CliCodeApproval(
        CodeApprovalService(),
        input_fn=MagicMock(return_value="n"),
        output_fn=MagicMock(),
    )

    result = cli.review(GeneratedCodeResult((_code(),)))

    assert result.items[0].status is GeneratedCodeStatus.REJECTED


def test_cli_invalid_input_never_auto_approves_and_stops_at_limit():
    input_fn = MagicMock(return_value="invalid")
    original = _code()
    cli = CliCodeApproval(CodeApprovalService(), input_fn, MagicMock())

    result = cli.review(GeneratedCodeResult((original,)))

    assert input_fn.call_count == MAX_APPROVAL_INPUT_ATTEMPTS
    assert result.items[0].status is GeneratedCodeStatus.REVIEW_REQUIRED


@pytest.mark.parametrize("risk", [CodeRiskLevel.HIGH, CodeRiskLevel.BLOCKED])
def test_cli_does_not_request_input_for_high_or_blocked_candidate(risk):
    input_fn = MagicMock(side_effect=AssertionError("input must not be called"))
    output_fn = MagicMock()

    result = CliCodeApproval(
        CodeApprovalService(), input_fn, output_fn
    ).review(GeneratedCodeResult((_code(risk),)))

    input_fn.assert_not_called()
    assert result.items[0].status is GeneratedCodeStatus.REVIEW_REQUIRED
    assert output_fn.called


def test_cli_reviews_multiple_candidates_independently_in_source_order():
    first = _code(source_index=2, code="print(2)")
    second = _code(source_index=0, code="print(0)")
    input_fn = MagicMock(side_effect=["y", "n"])

    result = CliCodeApproval(
        CodeApprovalService(), input_fn, MagicMock()
    ).review(GeneratedCodeResult((first, second)))

    assert result.items[0].status is GeneratedCodeStatus.REJECTED
    assert result.items[1].status is GeneratedCodeStatus.APPROVED
    assert input_fn.call_count == 2


@pytest.mark.parametrize(
    ("status", "label"),
    [
        (GeneratedCodeStatus.APPROVED, "状態：承認済み・未実行"),
        (GeneratedCodeStatus.REJECTED, "状態：拒否済み"),
    ],
)
def test_formatter_displays_decided_status(status, label):
    result = JudgeResult(
        category="Rev",
        answer="answer",
        generated_code=GeneratedCodeResult((_code(status=status),)),
    )

    assert label in ResultFormatter().format(result)


def test_formatter_says_approved_code_is_still_unexecuted():
    result = JudgeResult(
        category="Rev",
        answer="answer",
        generated_code=GeneratedCodeResult(
            (_code(status=GeneratedCodeStatus.APPROVED),)
        ),
    )

    output = ResultFormatter().format(result)

    assert "承認済みですが、コードはまだ実行されていません。" in output
    assert "安全なコードです" not in output


def test_approval_implementation_does_not_execute_or_spawn_code():
    source = inspect.getsource(CodeApprovalService) + inspect.getsource(CliCodeApproval)

    assert "subprocess" not in source
    assert "eval(" not in source
    assert "exec(" not in source
    assert "compile(" not in source


def test_main_requests_approval_only_after_displaying_generated_result():
    generated = GeneratedCodeResult((_code(),))
    judge_result = JudgeResult(
        category="Rev",
        answer="answer",
        generated_code=generated,
    )
    with (
        patch("app.main.Config") as config_cls,
        patch("app.main.OpenAIClient"),
        patch("app.main.ChallengeService") as service_cls,
        patch("builtins.input", side_effect=["question", "", "y", "n"]),
        patch("builtins.print") as print_mock,
    ):
        config_cls.return_value.openai_api_key = "test-key"
        config_cls.return_value.openai_model = "test-model"
        service_cls.return_value.solve.return_value = judge_result

        main()

    printed = [str(call.args[0]) for call in print_mock.call_args_list if call.args]
    result_position = next(
        index for index, value in enumerate(printed) if "生成コード候補" in value
    )
    approval_position = next(
        index for index, value in enumerate(printed) if "隔離実行段階" in value
    )
    assert result_position < approval_position
    assert any("承認しました" in value for value in printed)
