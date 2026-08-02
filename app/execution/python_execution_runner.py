import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app.codegen.code_safety_result import CodeRiskLevel
from app.codegen.generated_code_result import (
    GeneratedCode,
    GeneratedCodeLanguage,
    GeneratedCodeStatus,
)
from app.execution.execution_result import (
    ExecutionFailureReason,
    ExecutionStatus,
    PythonExecutionResult,
)

DEFAULT_TIMEOUT_SECONDS = 3.0
MAX_TIMEOUT_SECONDS = 10.0
MAX_CODE_CHARACTERS = 20_000
MAX_STDOUT_BYTES = 64 * 1024
MAX_STDERR_BYTES = 64 * 1024
SCRIPT_NAME = "candidate.py"


class PythonExecutionRunner:
    """承認済みLOWコードだけを制限付き別プロセスで実行する。"""

    def __init__(self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        if timeout_seconds <= 0 or timeout_seconds > MAX_TIMEOUT_SECONDS:
            raise ValueError(
                f"timeout_secondsは0より大きく{MAX_TIMEOUT_SECONDS}以下にしてください。"
            )
        self._timeout_seconds = timeout_seconds

    def run(self, code: GeneratedCode) -> PythonExecutionResult:
        failure = self._validation_failure(code)
        if failure is not None:
            return self._rejected(failure)

        started_at = time.perf_counter()
        temporary_directory: tempfile.TemporaryDirectory[str] | None = None
        result: PythonExecutionResult
        try:
            temporary_directory = tempfile.TemporaryDirectory(
                prefix="aegis-code-"
            )
            directory = Path(temporary_directory.name)
            script_path = directory / SCRIPT_NAME
            script_path.write_text(code.code, encoding="utf-8")
            result = self._execute(script_path, directory, started_at)
        except Exception as error:  # noqa: BLE001 - 起動・一時領域失敗をDTO化
            result = self._failed(started_at, error)

        if temporary_directory is not None:
            try:
                temporary_directory.cleanup()
            except Exception:  # noqa: BLE001 - cleanup失敗をDTO化
                return PythonExecutionResult(
                    status=ExecutionStatus.FAILED,
                    started=result.started,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    exit_code=result.exit_code,
                    timed_out=result.timed_out,
                    duration_seconds=result.duration_seconds,
                    failure_reason=ExecutionFailureReason.CLEANUP_FAILED,
                    message="一時実行領域を削除できませんでした。",
                    output_truncated=result.output_truncated,
                    cleanup_succeeded=False,
                )
        return result

    def _execute(
        self,
        script_path: Path,
        directory: Path,
        started_at: float,
    ) -> PythonExecutionResult:
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            process = subprocess.Popen(
                [sys.executable, "-I", "-S", "-B", "-X", "utf8", SCRIPT_NAME],
                cwd=directory,
                env={},
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                shell=False,
                creationflags=creation_flags,
            )
            try:
                exit_code = process.wait(timeout=self._timeout_seconds)
                timed_out = False
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                exit_code = None
                timed_out = True
            stdout, stdout_truncated = self._read_limited(
                stdout_file, MAX_STDOUT_BYTES
            )
            stderr, stderr_truncated = self._read_limited(
                stderr_file, MAX_STDERR_BYTES
            )

        duration = time.perf_counter() - started_at
        truncated = stdout_truncated or stderr_truncated
        if timed_out:
            return PythonExecutionResult(
                ExecutionStatus.TIMED_OUT,
                True,
                stdout,
                stderr,
                None,
                True,
                duration,
                ExecutionFailureReason.TIMED_OUT,
                "実行時間の上限を超えたため停止しました。",
                truncated,
                True,
            )
        return PythonExecutionResult(
            ExecutionStatus.COMPLETED,
            True,
            stdout,
            stderr,
            exit_code,
            False,
            duration,
            ExecutionFailureReason.OUTPUT_LIMIT_EXCEEDED if truncated else None,
            "制限付き実行が完了しました。",
            truncated,
            True,
        )

    def _read_limited(self, stream, limit: int) -> tuple[str, bool]:
        stream.seek(0)
        content = stream.read(limit + 1)
        truncated = len(content) > limit
        return content[:limit].decode("utf-8", errors="replace"), truncated

    def _validation_failure(
        self,
        code: GeneratedCode,
    ) -> ExecutionFailureReason | None:
        if code.language is not GeneratedCodeLanguage.PYTHON:
            return ExecutionFailureReason.NOT_PYTHON
        if code.status is not GeneratedCodeStatus.APPROVED:
            return ExecutionFailureReason.NOT_APPROVED
        if code.safety is None:
            return ExecutionFailureReason.NO_SAFETY_RESULT
        if not code.safety.parseable:
            return ExecutionFailureReason.UNPARSEABLE
        if code.safety.overall_risk is not CodeRiskLevel.LOW:
            return ExecutionFailureReason.RISK_NOT_LOW
        if not isinstance(code.source_index, int) or code.source_index < 0:
            return ExecutionFailureReason.INVALID_INDEX
        if not code.code.strip():
            return ExecutionFailureReason.EMPTY_CODE
        if len(code.code) > MAX_CODE_CHARACTERS:
            return ExecutionFailureReason.CODE_TOO_LARGE
        return None

    def _rejected(
        self,
        reason: ExecutionFailureReason,
    ) -> PythonExecutionResult:
        return PythonExecutionResult(
            ExecutionStatus.REJECTED,
            False,
            "",
            "",
            None,
            False,
            0.0,
            reason,
            "実行条件を満たしていないため開始しませんでした。",
            False,
            True,
        )

    def _failed(
        self,
        started_at: float,
        error: Exception,
    ) -> PythonExecutionResult:
        return PythonExecutionResult(
            ExecutionStatus.FAILED,
            False,
            "",
            "",
            None,
            False,
            time.perf_counter() - started_at,
            ExecutionFailureReason.START_FAILED,
            f"制限付き実行を開始できませんでした：{type(error).__name__}",
            False,
            True,
        )
