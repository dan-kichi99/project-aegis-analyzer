import hashlib
import json
import math
import time
from collections.abc import Callable
from dataclasses import asdict

from app.benchmark.benchmark_case import BenchmarkCase, BenchmarkExpectedPath
from app.benchmark.benchmark_result import (
    BenchmarkCaseResult,
    BenchmarkCaseStatus,
    BenchmarkExecutionResult,
    BenchmarkRunResult,
    BenchmarkSummary,
)

CaseExecutor = Callable[[BenchmarkCase], BenchmarkExecutionResult]


class CtfBenchmarkRunner:
    def __init__(
        self,
        *,
        case_executor: CaseExecutor,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._case_executor = case_executor
        self._clock = clock

    def run(self, cases: tuple[BenchmarkCase, ...]) -> BenchmarkRunResult:
        self._validate_unique_ids(cases)
        first = self._run_cases(cases)
        second = self._run_cases(cases)
        reproducible = all(
            self._comparison_values(left) == self._comparison_values(right)
            for left, right in zip(first, second, strict=True)
        )
        return BenchmarkRunResult(
            results=first,
            summary=self._summarize(first, reproducible),
        )

    def _run_cases(
        self, cases: tuple[BenchmarkCase, ...]
    ) -> tuple[BenchmarkCaseResult, ...]:
        return tuple(self._run_case(case) for case in cases)

    def _run_case(self, case: BenchmarkCase) -> BenchmarkCaseResult:
        before = self._input_fingerprint(case)
        started = self._clock()
        try:
            execution = self._case_executor(case)
            if not isinstance(execution, BenchmarkExecutionResult):
                raise TypeError("case_executor must return BenchmarkExecutionResult.")
        except Exception as error:  # noqa: BLE001 - benchmark isolates case failures
            duration = max(0.0, self._clock() - started)
            reasons = ["ケース実行中に例外が発生しました。"]
            if before != self._input_fingerprint(case):
                reasons.append("入力DTOが変更されました。")
            return self._make_result(
                case=case,
                status=BenchmarkCaseStatus.ERROR,
                execution=None,
                duration=duration,
                exception_type=type(error).__name__,
                reasons=tuple(reasons),
            )
        duration = max(0.0, self._clock() - started)
        reasons = self._failure_reasons(case, execution)
        if before != self._input_fingerprint(case):
            reasons.append("入力DTOが変更されました。")
        status = BenchmarkCaseStatus.PASSED
        if duration > case.max_duration_seconds:
            status = BenchmarkCaseStatus.TIMED_OUT
            reasons.append("実行時間上限を超過しました。")
        elif reasons:
            status = BenchmarkCaseStatus.FAILED
        return self._make_result(
            case=case,
            status=status,
            execution=execution,
            duration=duration,
            exception_type=None,
            reasons=tuple(reasons),
        )

    @staticmethod
    def _failure_reasons(
        case: BenchmarkCase, execution: BenchmarkExecutionResult
    ) -> list[str]:
        reasons: list[str] = []
        if execution.actual_path is not case.expected_path:
            reasons.append("期待した解析経路と一致しません。")
        if case.expected_flag is not None and execution.actual_flag != case.expected_flag:
            reasons.append("期待したFlagと一致しません。")
        if case.expected_flag is None and execution.actual_flag is not None:
            reasons.append("予期しないFlagが確定されました。")
        if (
            case.expected_ai_calls is not None
            and execution.ai_calls != case.expected_ai_calls
        ):
            reasons.append("AI呼び出し回数が一致しません。")
        if (
            case.expected_tool_calls is not None
            and execution.external_tool_calls != case.expected_tool_calls
        ):
            reasons.append("Tool呼び出し回数が一致しません。")
        if case.expected_agent_types and execution.agent_types != case.expected_agent_types:
            reasons.append("期待したAgent実行と一致しません。")
        return reasons

    def _make_result(
        self,
        *,
        case: BenchmarkCase,
        status: BenchmarkCaseStatus,
        execution: BenchmarkExecutionResult | None,
        duration: float,
        exception_type: str | None,
        reasons: tuple[str, ...],
    ) -> BenchmarkCaseResult:
        actual_flag = execution.actual_flag if execution else None
        flag_correct = (
            actual_flag == case.expected_flag if case.expected_flag is not None else None
        )
        false_positive = case.expected_flag is None and actual_flag is not None
        values = {
            "case_id": case.case_id,
            "status": status.value,
            "actual_path": execution.actual_path.value if execution else None,
            "solved": execution.solved if execution else False,
            "actual_flag": actual_flag,
            "flag_correct": flag_correct,
            "false_positive": false_positive,
            "ai_calls": execution.ai_calls if execution else 0,
            "agent_runs": execution.agent_runs if execution else 0,
            "tool_calls": execution.external_tool_calls if execution else 0,
            "failure_reasons": reasons,
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                values, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()
        ).hexdigest()
        return BenchmarkCaseResult(
            case_id=case.case_id,
            status=status,
            actual_path=execution.actual_path if execution else None,
            solved=execution.solved if execution else False,
            actual_flag=actual_flag,
            flag_correct=flag_correct,
            false_positive=false_positive,
            ai_calls=execution.ai_calls if execution else 0,
            agent_runs=execution.agent_runs if execution else 0,
            external_tool_calls=execution.external_tool_calls if execution else 0,
            duration_seconds=duration,
            exception_type=exception_type,
            failure_reasons=reasons,
            fingerprint=fingerprint,
        )

    @staticmethod
    def _input_fingerprint(case: BenchmarkCase) -> str:
        payload = asdict(case)
        payload["category"] = case.category.value
        payload["expected_path"] = case.expected_path.value
        payload["expected_agent_types"] = [item.value for item in case.expected_agent_types]
        payload["files"] = [
            {
                "name": item.name,
                "path": str(item.path),
                "size": item.size,
                "extension": item.extension,
                "content": hashlib.sha256(item.content).hexdigest(),
            }
            for item in case.files
        ]
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()

    @staticmethod
    def _comparison_values(result: BenchmarkCaseResult) -> tuple[object, ...]:
        return (
            result.status, result.actual_path, result.solved, result.actual_flag,
            result.flag_correct, result.false_positive, result.ai_calls,
            result.agent_runs, result.external_tool_calls, result.failure_reasons,
            result.fingerprint,
        )

    @staticmethod
    def _validate_unique_ids(cases: tuple[BenchmarkCase, ...]) -> None:
        ids = [case.case_id for case in cases]
        if len(ids) != len(set(ids)):
            raise ValueError("case_id must be unique.")

    @staticmethod
    def _summarize(
        results: tuple[BenchmarkCaseResult, ...], reproducible: bool
    ) -> BenchmarkSummary:
        durations = sorted(result.duration_seconds for result in results)
        total = len(results)
        path_counts = {
            path: sum(result.actual_path is path for result in results)
            for path in BenchmarkExpectedPath
        }
        # Errors have no actual path; account for them as safe failures in the summary.
        path_counts[BenchmarkExpectedPath.SAFE_FAILURE] += sum(
            result.actual_path is None for result in results
        )
        return BenchmarkSummary(
            total_cases=total,
            passed_cases=sum(r.status is BenchmarkCaseStatus.PASSED for r in results),
            failed_cases=sum(r.status is BenchmarkCaseStatus.FAILED for r in results),
            error_cases=sum(r.status is BenchmarkCaseStatus.ERROR for r in results),
            timed_out_cases=sum(r.status is BenchmarkCaseStatus.TIMED_OUT for r in results),
            local_solution_cases=path_counts[BenchmarkExpectedPath.LOCAL_SOLUTION],
            agent_solution_cases=path_counts[BenchmarkExpectedPath.AGENT_SOLUTION],
            ai_fallback_cases=path_counts[BenchmarkExpectedPath.AI_FALLBACK],
            unresolved_cases=path_counts[BenchmarkExpectedPath.UNRESOLVED],
            safe_failure_cases=path_counts[BenchmarkExpectedPath.SAFE_FAILURE],
            false_positive_cases=sum(r.false_positive for r in results),
            incorrect_flag_cases=sum(r.flag_correct is False for r in results),
            total_ai_calls=sum(r.ai_calls for r in results),
            total_agent_runs=sum(r.agent_runs for r in results),
            total_external_tool_calls=sum(r.external_tool_calls for r in results),
            average_duration_seconds=sum(durations) / total if total else 0.0,
            max_duration_seconds=max(durations, default=0.0),
            p95_duration_seconds=(durations[math.ceil(0.95 * total) - 1] if total else 0.0),
            reproducible=reproducible,
            deterministic=reproducible,
        )
