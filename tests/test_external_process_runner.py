import inspect
import os
import subprocess
import sys
import tempfile
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.external_tools import (
    ExternalProcessRequest,
    ExternalProcessResult,
    ExternalProcessRunner,
    ExternalProcessStatus,
)
from app.external_tools.process_request import MAX_STDERR_BYTES, MAX_STDOUT_BYTES


def _request(tmp_path, *arguments, **changes):
    values = {
        "executable": Path(sys.executable).resolve(),
        "arguments": tuple(arguments),
        "working_directory": tmp_path.resolve(),
        "timeout_seconds": 2.0,
        "max_stdout_bytes": 65_536,
        "max_stderr_bytes": 65_536,
    }
    values.update(changes)
    return ExternalProcessRequest(**values)


def _result():
    return ExternalProcessResult(
        ExternalProcessStatus.COMPLETED,
        True,
        str(Path(sys.executable).resolve()),
        ("-c", "pass"),
        "",
        "",
        0,
        0.01,
        False,
        False,
        False,
        None,
        None,
    )


def test_request_and_result_are_frozen_and_slotted(tmp_path):
    request = _request(tmp_path, "-c", "pass")
    result = ExternalProcessRunner().run(request)
    for value in (request, result):
        assert not hasattr(value, "__dict__")
        with pytest.raises(FrozenInstanceError):
            value.__setattr__(next(iter(value.__slots__)), None)


def test_process_status_has_only_required_values():
    assert tuple(item.value for item in ExternalProcessStatus) == (
        "completed",
        "timed_out",
        "failed",
        "rejected",
    )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("executable", Path("relative.exe"), "executable"),
        ("working_directory", Path("relative"), "working_directory"),
        ("arguments", ["not", "tuple"], "tuple"),
        ("timeout_seconds", 0, "timeout"),
        ("timeout_seconds", 10.1, "timeout"),
        ("timeout_seconds", True, "timeout"),
        ("max_stdout_bytes", 0, "max_stdout"),
        ("max_stdout_bytes", 65_537, "max_stdout"),
        ("max_stderr_bytes", 65_537, "max_stderr"),
        ("max_stderr_bytes", False, "max_stderr"),
    ],
)
def test_request_rejects_invalid_paths_numeric_limits_and_argument_container(
    tmp_path, field, value, match
):
    with pytest.raises(ValueError, match=match):
        replace(_request(tmp_path), **{field: value})


def test_request_validates_argument_count_length_type_and_nul(tmp_path):
    with pytest.raises(ValueError, match="50"):
        _request(tmp_path, *("x" for _ in range(51)))
    with pytest.raises(ValueError, match="4096"):
        _request(tmp_path, "x" * 4097)
    with pytest.raises(ValueError, match="文字列"):
        replace(_request(tmp_path), arguments=(1,))
    with pytest.raises(ValueError, match="NUL"):
        _request(tmp_path, "before\0after")
    assert _request(tmp_path, "").arguments == ("",)


def test_request_accepts_exact_default_output_limits(tmp_path):
    request = _request(
        tmp_path,
        max_stdout_bytes=MAX_STDOUT_BYTES,
        max_stderr_bytes=MAX_STDERR_BYTES,
    )
    assert request.max_stdout_bytes == 65_536
    assert request.max_stderr_bytes == 65_536


def test_result_validates_output_error_and_duration_limits():
    result = _result()
    for field in ("stdout", "stderr"):
        with pytest.raises(ValueError, match=field):
            replace(result, **{field: "x" * 65_537})
    with pytest.raises(ValueError, match="error_message"):
        replace(result, error_message="x" * 501)
    for duration in (-1, float("nan"), float("inf"), True):
        with pytest.raises(ValueError, match="duration"):
            replace(result, duration_seconds=duration)


def test_absolute_executable_runs_with_ordered_arguments_and_cwd(tmp_path):
    request = _request(
        tmp_path,
        "-c",
        "import os,sys; print(sys.argv[1:]); print(os.getcwd())",
        "first",
        "second",
    )
    result = ExternalProcessRunner().run(request)
    assert result.status is ExternalProcessStatus.COMPLETED
    assert result.started
    assert result.exit_code == 0
    assert result.arguments == request.arguments
    assert "['first', 'second']" in result.stdout
    assert str(tmp_path.resolve()) in result.stdout
    assert result.executable == str(request.executable)


def test_nonzero_exit_is_completed_and_stdout_stderr_are_captured(tmp_path):
    result = ExternalProcessRunner().run(
        _request(
            tmp_path,
            "-c",
            "import sys; print('out'); print('err', file=sys.stderr); raise SystemExit(7)",
        )
    )
    assert result.status is ExternalProcessStatus.COMPLETED
    assert result.started and not result.timed_out
    assert result.exit_code == 7
    assert result.stdout.splitlines() == ["out"]
    assert result.stderr.splitlines() == ["err"]


def test_invalid_utf8_is_decoded_with_replacement(tmp_path):
    result = ExternalProcessRunner().run(
        _request(tmp_path, "-c", "import os; os.write(1, bytes([255]))")
    )
    assert result.status is ExternalProcessStatus.COMPLETED
    assert "\ufffd" in result.stdout


def test_stdin_is_devnull_and_does_not_wait_for_parent(tmp_path):
    result = ExternalProcessRunner().run(
        _request(tmp_path, "-c", "input()", timeout_seconds=1)
    )
    assert result.status is ExternalProcessStatus.COMPLETED
    assert result.exit_code != 0
    assert "EOFError" in result.stderr


def test_parent_secrets_and_path_are_not_inherited(tmp_path):
    source = (
        "import os; "
        "print(os.getenv('OPENAI_API_KEY')); "
        "print(os.getenv('AWS_SECRET_ACCESS_KEY')); "
        "print(os.getenv('GITHUB_TOKEN')); "
        "print(os.getenv('PATH'))"
    )
    with patch.dict(
        os.environ,
        {
            "OPENAI_API_KEY": "openai-secret",
            "AWS_SECRET_ACCESS_KEY": "aws-secret",
            "GITHUB_TOKEN": "github-secret",
            "PATH": "parent-secret-path",
        },
    ):
        result = ExternalProcessRunner().run(_request(tmp_path, "-c", source))
    assert result.stdout.splitlines() == ["None", "None", "None", "None"]
    assert "secret" not in result.stdout


def test_timeout_kills_process_and_keeps_prior_output(tmp_path):
    result = ExternalProcessRunner().run(
        _request(
            tmp_path,
            "-c",
            "import os,time; os.write(1, b'before-timeout\\n'); time.sleep(2)",
            timeout_seconds=0.1,
        )
    )
    assert result.status is ExternalProcessStatus.TIMED_OUT
    assert result.started and result.timed_out
    assert result.exit_code is None
    assert "before-timeout" in result.stdout
    assert result.error_type == "TimeoutExpired"


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_output_is_truncated_to_requested_byte_limit(tmp_path, stream):
    descriptor = 1 if stream == "stdout" else 2
    result = ExternalProcessRunner().run(
        _request(
            tmp_path,
            "-c",
            f"import os; os.write({descriptor}, b'x' * 20)",
            max_stdout_bytes=10,
            max_stderr_bytes=10,
        )
    )
    assert getattr(result, stream) == "x" * 10
    assert getattr(result, f"{stream}_truncated") is True


def test_default_limits_truncate_both_streams_with_result_character_bounds(tmp_path):
    result = ExternalProcessRunner().run(
        _request(
            tmp_path,
            "-c",
            "import os; os.write(1, b'o' * 65537); os.write(2, b'e' * 65537)",
        )
    )
    assert len(result.stdout) == 65_536
    assert len(result.stderr) == 65_536
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True


def test_invalid_utf8_near_output_limit_is_safely_decoded_and_truncated(tmp_path):
    result = ExternalProcessRunner().run(
        _request(
            tmp_path,
            "-c",
            "import os; os.write(1, b'x' * 65535 + bytes([255]) + b'extra')",
        )
    )
    assert result.status is ExternalProcessStatus.COMPLETED
    assert len(result.stdout) <= 65_536
    assert "\ufffd" in result.stdout
    assert result.stdout_truncated is True


def test_missing_or_directory_executable_is_rejected(tmp_path):
    missing = tmp_path / "missing.exe"
    missing_result = ExternalProcessRunner().run(
        _request(tmp_path, executable=missing.resolve())
    )
    directory_result = ExternalProcessRunner().run(
        _request(tmp_path, executable=tmp_path.resolve())
    )
    for result in (missing_result, directory_result):
        assert result.status is ExternalProcessStatus.REJECTED
        assert not result.started


def test_invalid_working_directories_are_rejected(tmp_path):
    missing = (tmp_path / "missing").resolve()
    file_path = tmp_path / "file.txt"
    file_path.write_text("file", encoding="utf-8")
    for directory in (missing, file_path.resolve()):
        result = ExternalProcessRunner().run(
            _request(tmp_path, working_directory=directory)
        )
        assert result.status is ExternalProcessStatus.REJECTED
        assert not result.started


def test_symlink_executable_and_working_directory_are_rejected(tmp_path):
    request = _request(tmp_path)
    with patch.object(Path, "is_symlink", return_value=True):
        executable_result = ExternalProcessRunner().run(request)
    checks = iter((False, True))
    with patch.object(Path, "is_symlink", side_effect=lambda: next(checks)):
        directory_result = ExternalProcessRunner().run(request)
    assert executable_result.status is ExternalProcessStatus.REJECTED
    assert directory_result.status is ExternalProcessStatus.REJECTED


def test_popen_failure_is_structured_and_base_exceptions_propagate(tmp_path):
    request = _request(tmp_path, "-c", "pass")
    with patch(
        "app.external_tools.process_runner.subprocess.Popen",
        side_effect=OSError("start failed"),
    ):
        failed = ExternalProcessRunner().run(request)
    assert failed.status is ExternalProcessStatus.FAILED
    assert not failed.started
    assert failed.error_type == "OSError"
    assert "start failed" in failed.error_message
    for error in (KeyboardInterrupt(), SystemExit()):
        with (
            patch(
                "app.external_tools.process_runner.subprocess.Popen",
                side_effect=error,
            ),
            pytest.raises(type(error)),
        ):
            ExternalProcessRunner().run(request)


def test_popen_uses_argv_shell_false_devnull_cwd_and_empty_environment(tmp_path):
    request = _request(tmp_path, "first", "second")
    process = MagicMock()
    process.wait.return_value = 0
    with patch(
        "app.external_tools.process_runner.subprocess.Popen", return_value=process
    ) as popen:
        ExternalProcessRunner().run(request)
    _, kwargs = popen.call_args
    assert popen.call_args.args[0] == [str(request.executable), "first", "second"]
    assert kwargs["shell"] is False
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["cwd"] == request.working_directory
    assert kwargs["env"] == {}


def test_timeout_path_calls_kill_and_wait_again(tmp_path):
    request = _request(tmp_path)
    process = MagicMock()
    process.wait.side_effect = [subprocess.TimeoutExpired("tool", 1), 0]
    with patch(
        "app.external_tools.process_runner.subprocess.Popen", return_value=process
    ):
        result = ExternalProcessRunner().run(request)
    assert result.status is ExternalProcessStatus.TIMED_OUT
    process.kill.assert_called_once_with()
    assert process.wait.call_count == 2


def test_temporary_output_files_are_closed_after_run(tmp_path):
    original = tempfile.TemporaryFile
    files = []

    def tracking_file():
        value = original()
        files.append(value)
        return value

    with patch("app.external_tools.process_runner.tempfile.TemporaryFile", tracking_file):
        result = ExternalProcessRunner().run(_request(tmp_path, "-c", "pass"))
    assert result.status is ExternalProcessStatus.COMPLETED
    assert len(files) == 2 and all(value.closed for value in files)


def test_runner_source_uses_no_shell_command_parent_path_or_adapter():
    source = inspect.getsource(
        sys.modules[ExternalProcessRunner.__module__]
    ).casefold()
    assert "shell=false" in source
    assert "subprocess.devnull" in source
    assert "env={}" in source
    assert "temporaryfile" in source
    assert "time.monotonic" in source
    for forbidden in (
        "shell=true",
        "os.system",
        "powershell",
        "cmd.exe",
        "bash",
        "os.environ",
        "environ.copy",
        "strings",
        "readelf",
        "objdump",
        "binwalk",
    ):
        assert forbidden not in source
