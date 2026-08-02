import inspect
import os
import sys
from dataclasses import fields
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.codegen.code_safety_result import CodeRiskLevel, CodeSafetyResult
from app.codegen.generated_code_result import (
    GeneratedCode,
    GeneratedCodeLanguage,
    GeneratedCodeResult,
    GeneratedCodeStatus,
)
from app.execution.cli_python_execution import (
    MAX_EXECUTION_INPUT_ATTEMPTS,
    CliPythonExecution,
)
from app.execution.execution_result import (
    ExecutionFailureReason,
    ExecutionStatus,
    PythonExecutionResult,
)
from app.execution.python_execution_runner import (
    MAX_CODE_CHARACTERS,
    MAX_STDERR_BYTES,
    MAX_STDOUT_BYTES,
    PythonExecutionRunner,
)
from app.utils.result_formatter import ResultFormatter


def _code(
    source: str = "print('hello')",
    risk: CodeRiskLevel = CodeRiskLevel.LOW,
    **changes,
) -> GeneratedCode:
    values = {
        "language": GeneratedCodeLanguage.PYTHON,
        "code": source,
        "purpose": "安全な固定テスト",
        "source_index": 0,
        "status": GeneratedCodeStatus.APPROVED,
        "safety": CodeSafetyResult(True, risk, ()),
    }
    values.update(changes)
    return GeneratedCode(**values)


def test_approved_low_python_code_runs_in_separate_process():
    original = _code()

    result = PythonExecutionRunner().run(original)

    assert result.status is ExecutionStatus.COMPLETED
    assert result.started is True
    assert result.stdout.splitlines() == ["hello"]
    assert result.stderr == ""
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.duration_seconds >= 0
    assert original.status is GeneratedCodeStatus.APPROVED


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"status": GeneratedCodeStatus.REVIEW_REQUIRED}, ExecutionFailureReason.NOT_APPROVED),
        ({"status": GeneratedCodeStatus.REJECTED}, ExecutionFailureReason.NOT_APPROVED),
        ({"language": GeneratedCodeLanguage.UNKNOWN}, ExecutionFailureReason.NOT_PYTHON),
        ({"safety": None}, ExecutionFailureReason.NO_SAFETY_RESULT),
        ({"safety": CodeSafetyResult(False, CodeRiskLevel.BLOCKED, ())}, ExecutionFailureReason.UNPARSEABLE),
        ({"safety": CodeSafetyResult(True, CodeRiskLevel.MEDIUM, ())}, ExecutionFailureReason.RISK_NOT_LOW),
        ({"safety": CodeSafetyResult(True, CodeRiskLevel.HIGH, ())}, ExecutionFailureReason.RISK_NOT_LOW),
        ({"safety": CodeSafetyResult(True, CodeRiskLevel.BLOCKED, ())}, ExecutionFailureReason.RISK_NOT_LOW),
        ({"code": " \n"}, ExecutionFailureReason.EMPTY_CODE),
        ({"source_index": -1}, ExecutionFailureReason.INVALID_INDEX),
        ({"code": "x" * (MAX_CODE_CHARACTERS + 1)}, ExecutionFailureReason.CODE_TOO_LARGE),
    ],
)
def test_invalid_candidate_is_rejected_without_starting(changes, reason):
    result = PythonExecutionRunner().run(_code(**changes))

    assert result.status is ExecutionStatus.REJECTED
    assert result.started is False
    assert result.failure_reason is reason
    assert result.duration_seconds == 0


def test_captures_stderr_and_nonzero_exit_code():
    result = PythonExecutionRunner().run(
        _code("import sys\nprint('problem', file=sys.stderr)\nraise SystemExit(7)")
    )

    assert result.stderr.splitlines() == ["problem"]
    assert result.exit_code == 7


def test_invalid_utf8_output_is_replaced_without_crashing():
    result = PythonExecutionRunner().run(
        _code("import sys\nsys.stdout.buffer.write(bytes([255]))")
    )

    assert result.status is ExecutionStatus.COMPLETED
    assert "�" in result.stdout


def test_stdin_is_disabled_and_input_does_not_wait_for_parent():
    result = PythonExecutionRunner(timeout_seconds=1).run(_code("input()"))

    assert result.timed_out is False
    assert result.exit_code != 0
    assert "EOFError" in result.stderr


def test_timeout_stops_process_and_cleans_temporary_directory():
    result = PythonExecutionRunner(timeout_seconds=0.1).run(
        _code("while True:\n    pass")
    )

    assert result.status is ExecutionStatus.TIMED_OUT
    assert result.timed_out is True
    assert result.exit_code is None
    assert result.failure_reason is ExecutionFailureReason.TIMED_OUT
    assert result.cleanup_succeeded is True


@pytest.mark.parametrize(
    ("stream", "limit"),
    [("stdout", MAX_STDOUT_BYTES), ("stderr", MAX_STDERR_BYTES)],
)
def test_output_is_truncated_to_dto_byte_limit(stream, limit):
    target = "sys.stdout" if stream == "stdout" else "sys.stderr"
    source = f"import sys\n{target}.write('x' * {limit + 10})"

    result = PythonExecutionRunner().run(_code(source))

    assert len(getattr(result, stream).encode("utf-8")) <= limit
    assert result.output_truncated is True
    assert result.failure_reason is ExecutionFailureReason.OUTPUT_LIMIT_EXCEEDED


def test_sensitive_parent_environment_is_not_inherited():
    source = (
        "import os\n"
        "print(os.getenv('OPENAI_API_KEY'))\n"
        "print(os.getenv('AWS_SECRET_ACCESS_KEY'))\n"
        "print(os.getenv('GITHUB_TOKEN'))"
    )
    with patch.dict(
        os.environ,
        {
            "OPENAI_API_KEY": "secret-openai",
            "AWS_SECRET_ACCESS_KEY": "secret-aws",
            "GITHUB_TOKEN": "secret-github",
        },
    ):
        result = PythonExecutionRunner().run(_code(source))

    assert result.stdout.splitlines() == ["None", "None", "None"]
    assert "secret" not in result.stdout


def test_runner_source_fixes_interpreter_flags_and_disables_shell_and_stdin():
    source = inspect.getsource(PythonExecutionRunner)

    assert "sys.executable" in source
    assert '"-I"' in source
    assert '"-S"' in source
    assert '"-B"' in source
    assert "shell=False" in source
    assert "subprocess.DEVNULL" in source
    assert "TemporaryDirectory" in source
    assert 'SCRIPT_NAME = "candidate.py"' in inspect.getsource(
        sys.modules[PythonExecutionRunner.__module__]
    )


def test_start_failure_is_returned_without_leaking_exception():
    with patch("app.execution.python_execution_runner.subprocess.Popen", side_effect=OSError):
        result = PythonExecutionRunner().run(_code())

    assert result.status is ExecutionStatus.FAILED
    assert result.failure_reason is ExecutionFailureReason.START_FAILED
    assert result.cleanup_succeeded is True


def test_result_contains_neither_code_nor_temporary_path_fields():
    names = {field.name for field in fields(PythonExecutionResult)}

    assert "code" not in names
    assert "path" not in names
    assert "temporary_directory" not in names


def test_cli_requires_second_explicit_yes_before_calling_runner():
    runner = MagicMock()
    runner.run.return_value = MagicMock(spec=PythonExecutionResult)
    input_fn = MagicMock(return_value="Y")
    cli = CliPythonExecution(runner, input_fn, MagicMock())

    results = cli.run_approved(GeneratedCodeResult((_code(),)))

    input_fn.assert_called_once()
    runner.run.assert_called_once()
    assert len(results) == 1


@pytest.mark.parametrize("answer", ["n", "N", "", "invalid"])
def test_cli_does_not_execute_without_explicit_yes(answer):
    runner = MagicMock()
    input_fn = MagicMock(return_value=answer)

    results = CliPythonExecution(runner, input_fn, MagicMock()).run_approved(
        GeneratedCodeResult((_code(),))
    )

    runner.run.assert_not_called()
    assert results == ()
    expected = 1 if answer.casefold() == "n" else MAX_EXECUTION_INPUT_ATTEMPTS
    assert input_fn.call_count == expected


@pytest.mark.parametrize(
    "code",
    [
        _code(risk=CodeRiskLevel.MEDIUM),
        _code(risk=CodeRiskLevel.HIGH),
        _code(risk=CodeRiskLevel.BLOCKED),
        _code(status=GeneratedCodeStatus.REVIEW_REQUIRED),
    ],
)
def test_cli_does_not_prompt_for_non_low_or_unapproved_candidate(code):
    runner = MagicMock()
    input_fn = MagicMock()

    results = CliPythonExecution(runner, input_fn, MagicMock()).run_approved(
        GeneratedCodeResult((code,))
    )

    input_fn.assert_not_called()
    runner.run.assert_not_called()
    assert results == ()


def test_execution_formatter_displays_result_and_limit_warning():
    result = PythonExecutionResult(
        ExecutionStatus.COMPLETED,
        True,
        "FLAG{display_only}\n",
        "",
        0,
        False,
        0.04,
        None,
        "完了",
        False,
        True,
    )

    output = ResultFormatter().format_execution(result)

    assert "コード実行結果" in output
    assert "状態：完了" in output
    assert "終了コード：0" in output
    assert "FLAG{display_only}" in output
    assert "完全なサンドボックスではありません" in output
    assert "まだ正解判定されていません" in output


def test_actual_execution_removes_candidate_directory(monkeypatch):
    created: list[Path] = []
    real_temporary_directory = __import__("tempfile").TemporaryDirectory

    def recording_directory(*args, **kwargs):
        temporary = real_temporary_directory(*args, **kwargs)
        created.append(Path(temporary.name))
        return temporary

    monkeypatch.setattr(
        "app.execution.python_execution_runner.tempfile.TemporaryDirectory",
        recording_directory,
    )

    result = PythonExecutionRunner().run(_code())

    assert result.cleanup_succeeded is True
    assert created and all(not path.exists() for path in created)


def test_cleanup_failure_is_returned_as_structured_result(monkeypatch):
    real_temporary_directory = __import__("tempfile").TemporaryDirectory

    class CleanupFailureDirectory:
        def __init__(self, *args, **kwargs):
            self._temporary = real_temporary_directory(*args, **kwargs)
            self.name = self._temporary.name

        def cleanup(self):
            self._temporary.cleanup()
            raise OSError("simulated cleanup reporting failure")

    monkeypatch.setattr(
        "app.execution.python_execution_runner.tempfile.TemporaryDirectory",
        CleanupFailureDirectory,
    )

    result = PythonExecutionRunner().run(_code())

    assert result.status is ExecutionStatus.FAILED
    assert result.failure_reason is ExecutionFailureReason.CLEANUP_FAILED
    assert result.cleanup_succeeded is False
