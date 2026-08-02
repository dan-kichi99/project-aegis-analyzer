import subprocess
import tempfile
import time
from typing import BinaryIO

from app.external_tools.process_request import ExternalProcessRequest
from app.external_tools.process_result import (
    MAX_PROCESS_ERROR_CHARACTERS,
    MAX_PROCESS_RESULT_OUTPUT_CHARACTERS,
    ExternalProcessResult,
    ExternalProcessStatus,
)


class ExternalProcessRunner:
    """絶対パスで指定されたProcessをShellなしで制限付き実行する。"""

    def run(self, request: ExternalProcessRequest) -> ExternalProcessResult:
        validation_error = self._validation_error(request)
        if validation_error is not None:
            return self._result(
                request,
                ExternalProcessStatus.REJECTED,
                False,
                0.0,
                error_type="ValidationError",
                error_message=validation_error,
            )

        started_at = time.monotonic()
        started = False
        try:
            with (
                tempfile.TemporaryFile() as stdout_file,
                tempfile.TemporaryFile() as stderr_file,
            ):
                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                process = subprocess.Popen(
                    [str(request.executable), *request.arguments],
                    cwd=request.working_directory,
                    env={},
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    shell=False,
                    creationflags=creation_flags,
                )
                started = True
                timed_out = False
                timeout_error: str | None = None
                try:
                    exit_code = process.wait(timeout=request.timeout_seconds)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    exit_code = None
                    try:
                        process.kill()
                        process.wait()
                    except Exception as error:  # noqa: BLE001 - kill失敗をDTOへ制限
                        timeout_error = self._error_text(error)
                stdout, stdout_truncated = self._read_limited(
                    stdout_file, request.max_stdout_bytes
                )
                stderr, stderr_truncated = self._read_limited(
                    stderr_file, request.max_stderr_bytes
                )
            duration = time.monotonic() - started_at
            if timed_out:
                return self._result(
                    request,
                    ExternalProcessStatus.TIMED_OUT,
                    True,
                    duration,
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=None,
                    timed_out=True,
                    stdout_truncated=stdout_truncated,
                    stderr_truncated=stderr_truncated,
                    error_type="TimeoutExpired",
                    error_message=timeout_error or "Processがタイムアウトしました。",
                )
            return self._result(
                request,
                ExternalProcessStatus.COMPLETED,
                True,
                duration,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                stdout_truncated=stdout_truncated,
                stderr_truncated=stderr_truncated,
            )
        except Exception as error:  # noqa: BLE001 - 起動・取得失敗をDTOへ構造化
            return self._result(
                request,
                ExternalProcessStatus.FAILED,
                started,
                time.monotonic() - started_at,
                error_type=type(error).__name__,
                error_message=self._error_text(error),
            )

    def _validation_error(self, request: ExternalProcessRequest) -> str | None:
        executable = request.executable
        if executable.is_symlink():
            return "executableにsymlinkは指定できません。"
        if not executable.exists():
            return "executableが存在しません。"
        if not executable.is_file():
            return "executableはファイルで指定してください。"
        directory = request.working_directory
        if directory.is_symlink():
            return "working_directoryにsymlinkは指定できません。"
        if not directory.exists():
            return "working_directoryが存在しません。"
        if not directory.is_dir():
            return "working_directoryはディレクトリで指定してください。"
        return None

    def _read_limited(self, stream: BinaryIO, limit: int) -> tuple[str, bool]:
        stream.seek(0)
        content = stream.read(limit + 1)
        byte_truncated = len(content) > limit
        decoded = content[:limit].decode("utf-8", errors="replace")
        character_truncated = len(decoded) > MAX_PROCESS_RESULT_OUTPUT_CHARACTERS
        return (
            decoded[:MAX_PROCESS_RESULT_OUTPUT_CHARACTERS],
            byte_truncated or character_truncated,
        )

    def _error_text(self, error: Exception) -> str:
        return f"{type(error).__name__}: {error}"[:MAX_PROCESS_ERROR_CHARACTERS]

    def _result(
        self,
        request: ExternalProcessRequest,
        status: ExternalProcessStatus,
        started: bool,
        duration_seconds: float,
        *,
        stdout: str = "",
        stderr: str = "",
        exit_code: int | None = None,
        timed_out: bool = False,
        stdout_truncated: bool = False,
        stderr_truncated: bool = False,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> ExternalProcessResult:
        return ExternalProcessResult(
            status=status,
            started=started,
            executable=str(request.executable),
            arguments=request.arguments,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            duration_seconds=max(duration_seconds, 0.0),
            timed_out=timed_out,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            error_type=error_type,
            error_message=error_message,
        )
