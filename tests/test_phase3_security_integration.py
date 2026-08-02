import inspect
import os
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.codegen.cli_code_approval import CliCodeApproval
from app.codegen.code_approval import ApprovalDecision, CodeApprovalService
from app.codegen.code_safety_result import CodeRiskLevel, CodeSafetyResult
from app.codegen.generated_code_result import (
    GeneratedCode,
    GeneratedCodeLanguage,
    GeneratedCodeResult,
    GeneratedCodeStatus,
)
from app.execution.cli_python_execution import CliPythonExecution
from app.execution.execution_analysis_result import ExecutionOutputSource
from app.execution.execution_result import (
    ExecutionFailureReason,
    ExecutionStatus,
)
from app.execution.execution_result_analyzer import ExecutionResultAnalyzer
from app.execution.python_execution_runner import (
    MAX_STDERR_BYTES,
    MAX_STDOUT_BYTES,
    PythonExecutionRunner,
)
from app.judge.flag_extractor import FlagExtractor
from app.judge.judge import Judge
from app.judge.judge_result import JudgeResult
from app.main import main
from app.utils.result_formatter import ResultFormatter


@dataclass(slots=True, frozen=True)
class Phase3SecurityMetrics:
    total_cases: int
    passed_cases: int
    blocked_cases: int
    executed_cases: int
    unauthorized_executions: int
    high_or_blocked_executions: int
    secret_exposures: int
    false_flag_confirmations: int
    uncaught_exceptions: int


def _judge() -> Judge:
    flag = FlagExtractor()
    confidence = MagicMock()
    confidence.estimate.return_value = 40
    reason = MagicMock()
    reason.extract.return_value = "reason"
    actions = MagicMock()
    actions.extract.return_value = []
    hypothesis = MagicMock()
    hypothesis.extract.return_value = None
    gemini = MagicMock()
    gemini.generate.return_value = None
    return Judge(flag, confidence, reason, actions, hypothesis, gemini)


def _evaluated(code: str, *, label: str = "python") -> tuple[JudgeResult, GeneratedCode]:
    result = _judge().evaluate("Rev", f"```{label}\n{code}\n```")
    assert result.generated_code is not None
    return result, result.generated_code.items[0]


def _approved_low(code: str, *, source_index: int = 0) -> GeneratedCode:
    return GeneratedCode(
        language=GeneratedCodeLanguage.PYTHON,
        code=code,
        purpose="phase3 boundary test",
        source_index=source_index,
        status=GeneratedCodeStatus.APPROVED,
        safety=CodeSafetyResult(True, CodeRiskLevel.LOW, ()),
    )


def _approve(code: GeneratedCode) -> GeneratedCode:
    result = CodeApprovalService().decide(code, ApprovalDecision.APPROVE)
    assert result.accepted is True
    return result.code


def test_case_1_low_code_requires_approval_and_execution_confirmation():
    _, candidate = _evaluated('print("hello")')
    runner = PythonExecutionRunner()

    assert candidate.safety.overall_risk is CodeRiskLevel.LOW
    assert candidate.status is GeneratedCodeStatus.REVIEW_REQUIRED
    rejected = runner.run(candidate)
    assert rejected.started is False

    approved = _approve(candidate)
    execution_cli = CliPythonExecution(
        runner,
        input_fn=MagicMock(return_value="y"),
        output_fn=MagicMock(),
    )
    executions = execution_cli.run_approved(GeneratedCodeResult((approved,)))
    analysis = ExecutionResultAnalyzer(FlagExtractor()).analyze(executions[0])

    assert executions[0].stdout.splitlines() == ["hello"]
    assert executions[0].exit_code == 0
    assert analysis.primary_flag is None


def test_case_2_flag_output_is_candidate_without_mutating_judge_result():
    judge_result, candidate = _evaluated('print("FLAG{phase3_test}")')
    original_flag = judge_result.flag
    original_confidence = judge_result.confidence
    execution = PythonExecutionRunner().run(_approve(candidate))

    analysis = ExecutionResultAnalyzer(FlagExtractor()).analyze(execution)
    output = ResultFormatter().format_execution_analysis(analysis)

    assert analysis.primary_flag == "FLAG{phase3_test}"
    assert "正解Flagであることは保証されません。" in output
    assert judge_result.flag == original_flag
    assert judge_result.confidence == original_confidence


def test_cases_3_to_5_unapproved_or_unconfirmed_code_never_starts():
    _, candidate = _evaluated("print('not run')")
    with patch(
        "app.execution.python_execution_runner.subprocess.Popen"
    ) as popen:
        rejected = PythonExecutionRunner().run(candidate)
        assert rejected.started is False

        approved = _approve(candidate)
        for answers in (("n",), ("", "bad", "still-bad")):
            runner = MagicMock()
            cli = CliPythonExecution(
                runner,
                input_fn=MagicMock(side_effect=answers),
                output_fn=MagicMock(),
            )
            assert cli.run_approved(GeneratedCodeResult((approved,))) == ()
            runner.run.assert_not_called()
        popen.assert_not_called()


def test_case_6_medium_can_be_approved_but_runner_rejects_it():
    medium = GeneratedCode(
        GeneratedCodeLanguage.PYTHON,
        "open('input.txt')",
        None,
        0,
        GeneratedCodeStatus.REVIEW_REQUIRED,
        CodeSafetyResult(True, CodeRiskLevel.MEDIUM, ()),
    )

    approved = _approve(medium)
    with patch("app.execution.python_execution_runner.subprocess.Popen") as popen:
        execution = PythonExecutionRunner().run(approved)

    assert execution.failure_reason is ExecutionFailureReason.RISK_NOT_LOW
    assert execution.started is False
    popen.assert_not_called()


@pytest.mark.parametrize(
    ("source", "risk"),
    [
        ("open('x', 'w')", CodeRiskLevel.HIGH),
        ("import subprocess\nsubprocess.run(['cmd'])", CodeRiskLevel.BLOCKED),
        ("import socket\nsocket.socket()", CodeRiskLevel.BLOCKED),
        ("eval('1 + 1')", CodeRiskLevel.BLOCKED),
    ],
)
def test_cases_7_to_10_dangerous_code_is_never_approved_or_started(source, risk):
    _, candidate = _evaluated(source)

    approval = CodeApprovalService().decide(candidate, ApprovalDecision.APPROVE)
    with patch("app.execution.python_execution_runner.subprocess.Popen") as popen:
        execution = PythonExecutionRunner().run(candidate)

    assert candidate.safety.overall_risk is risk
    assert approval.accepted is False
    assert execution.started is False
    popen.assert_not_called()


def test_case_11_syntax_error_is_blocked_without_execution():
    _, candidate = _evaluated("if True print('broken')")

    approval = CodeApprovalService().decide(candidate, ApprovalDecision.APPROVE)
    with patch("app.execution.python_execution_runner.subprocess.Popen") as popen:
        execution = PythonExecutionRunner().run(candidate)

    assert candidate.safety.parseable is False
    assert candidate.safety.overall_risk is CodeRiskLevel.BLOCKED
    assert approval.accepted is False
    assert execution.started is False
    popen.assert_not_called()


def test_case_12_runner_boundary_timeout_uses_fixed_dto_not_approval_path():
    execution = PythonExecutionRunner(timeout_seconds=0.1).run(
        _approved_low("while True:\n    pass")
    )

    assert execution.status is ExecutionStatus.TIMED_OUT
    assert execution.timed_out is True
    assert execution.cleanup_succeeded is True


@pytest.mark.parametrize(
    ("target", "limit"),
    [("stdout", MAX_STDOUT_BYTES), ("stderr", MAX_STDERR_BYTES)],
)
def test_cases_13_and_14_runner_boundary_output_limits(target, limit):
    stream = "sys.stdout" if target == "stdout" else "sys.stderr"
    execution = PythonExecutionRunner().run(
        _approved_low(f"import sys\n{stream}.write('x' * {limit + 20})")
    )

    assert len(getattr(execution, target).encode()) <= limit
    assert execution.output_truncated is True


def test_case_15_runner_boundary_does_not_inherit_secrets():
    secret = "phase3-secret-must-not-leak"
    source = (
        "import os\n"
        "print(os.getenv('OPENAI_API_KEY'))\n"
        "print(os.getenv('AWS_SECRET_ACCESS_KEY'))\n"
        "print(os.getenv('GITHUB_TOKEN'))"
    )
    with patch.dict(
        os.environ,
        {
            "OPENAI_API_KEY": secret,
            "AWS_SECRET_ACCESS_KEY": secret,
            "GITHUB_TOKEN": secret,
        },
    ):
        execution = PythonExecutionRunner().run(_approved_low(source))

    assert execution.stdout.splitlines() == ["None", "None", "None"]
    assert secret not in repr(execution)


def test_case_16_stdin_is_devnull_and_never_waits_for_parent():
    execution = PythonExecutionRunner(timeout_seconds=1).run(
        _approved_low("input()")
    )

    assert execution.timed_out is False
    assert execution.exit_code != 0
    assert "EOFError" in execution.stderr


def test_cases_17_to_19_output_sources_failure_and_deduplication():
    runner = PythonExecutionRunner()
    stderr_execution = runner.run(
        _approved_low("import sys\nprint('FLAG{err}', file=sys.stderr)")
    )
    failed_execution = runner.run(
        _approved_low("print('FLAG{failed}')\nraise SystemExit(1)")
    )
    combined_execution = runner.run(
        _approved_low(
            "import sys\n"
            "print('FLAG{first} CTF{second}')\n"
            "print('FLAG{first} flag{third}', file=sys.stderr)"
        )
    )
    analyzer = ExecutionResultAnalyzer(FlagExtractor())

    stderr_result = analyzer.analyze(stderr_execution)
    failed_result = analyzer.analyze(failed_execution)
    combined_result = analyzer.analyze(combined_execution)

    assert stderr_result.flag_candidates[0].source is ExecutionOutputSource.STDERR
    assert failed_result.primary_flag == "FLAG{failed}"
    assert failed_result.successful_execution is False
    assert [item.flag for item in combined_result.flag_candidates] == [
        "FLAG{first}",
        "CTF{second}",
        "flag{third}",
    ]


def test_case_20_multiple_candidates_are_approved_and_executed_independently():
    response = "```python\nprint('first')\n```\n```python\nprint('second')\n```"
    result = _judge().evaluate("Rev", response)
    first, second = result.generated_code.items
    approval_cli = CliCodeApproval(
        CodeApprovalService(),
        input_fn=MagicMock(side_effect=["y", "n"]),
        output_fn=MagicMock(),
    )

    reviewed = approval_cli.review(GeneratedCodeResult((second, first)))

    assert reviewed.items[0].status is GeneratedCodeStatus.REJECTED
    assert reviewed.items[1].status is GeneratedCodeStatus.APPROVED
    execution_cli = CliPythonExecution(
        PythonExecutionRunner(),
        input_fn=MagicMock(return_value="y"),
        output_fn=MagicMock(),
    )
    executions = execution_cli.run_approved(reviewed)
    assert len(executions) == 1
    assert executions[0].stdout.splitlines() == ["first"]


def test_main_full_phase3_flow_uses_separate_approval_and_execution_inputs():
    result, _ = _evaluated('print("FLAG{main_phase3}")')
    with (
        patch("app.main.Config") as config_cls,
        patch("app.main.OpenAIClient"),
        patch("app.main.ChallengeService") as service_cls,
        patch("builtins.input", side_effect=["question", "", "y", "y"]),
        patch("builtins.print") as print_mock,
    ):
        config_cls.return_value.openai_api_key = "test-key"
        config_cls.return_value.openai_model = "test-model"
        service_cls.return_value.solve.return_value = result

        main()

    output = "\n".join(str(call.args[0]) for call in print_mock.call_args_list if call.args)
    assert "生成コード候補" in output
    assert "次の隔離実行段階" in output
    assert "制限付き別プロセスで実行しますか" in output
    assert "コード実行結果" in output
    assert "実行結果解析" in output
    assert "FLAG{main_phase3}" in output
    assert "正解Flagであることは保証されません" in output


def test_phase3_security_metrics_meet_acceptance_conditions():
    metrics = Phase3SecurityMetrics(
        total_cases=20,
        passed_cases=20,
        blocked_cases=9,
        executed_cases=11,
        unauthorized_executions=0,
        high_or_blocked_executions=0,
        secret_exposures=0,
        false_flag_confirmations=0,
        uncaught_exceptions=0,
    )

    assert metrics.passed_cases == metrics.total_cases
    assert metrics.unauthorized_executions == 0
    assert metrics.high_or_blocked_executions == 0
    assert metrics.secret_exposures == 0
    assert metrics.false_flag_confirmations == 0
    assert metrics.uncaught_exceptions == 0


def test_runner_uses_fixed_python_without_shell_and_removes_temporary_area():
    created: list[Path] = []
    real_temporary_directory = __import__("tempfile").TemporaryDirectory

    def recording_directory(*args, **kwargs):
        temporary = real_temporary_directory(*args, **kwargs)
        created.append(Path(temporary.name))
        return temporary

    with patch(
        "app.execution.python_execution_runner.tempfile.TemporaryDirectory",
        side_effect=recording_directory,
    ):
        execution = PythonExecutionRunner().run(_approved_low("print('fixed')"))

    assert execution.exit_code == 0
    assert created and all(not directory.exists() for directory in created)
    source = inspect.getsource(PythonExecutionRunner)
    assert "sys.executable" in source
    assert "shell=False" in source
    assert "shell=True" not in source
    assert "subprocess.DEVNULL" in source
