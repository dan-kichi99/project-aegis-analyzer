from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.agents.agent_result import AgentType
from app.benchmark import (
    BenchmarkCase,
    BenchmarkCaseResult,
    BenchmarkCaseStatus,
    BenchmarkCategory,
    BenchmarkExecutionResult,
    BenchmarkExpectedPath,
    BenchmarkRunResult,
    BenchmarkSummary,
    CtfBenchmarkRunner,
)
from app.file.file_input import FileInput

CASE_NAMES = (
    ("crypto-direct", "直接Flag", BenchmarkCategory.CRYPTO),
    ("crypto-base64", "Base64内Flag", BenchmarkCategory.CRYPTO),
    ("crypto-hex", "Hex内Flag", BenchmarkCategory.CRYPTO),
    ("crypto-xor", "単一バイトXOR Flag", BenchmarkCategory.CRYPTO),
    ("crypto-rot13", "ROT13 Flag", BenchmarkCategory.CRYPTO),
    ("crypto-caesar", "Caesar非Flag", BenchmarkCategory.CRYPTO),
    ("crypto-rsa-pq", "RSA p/q指定Flag", BenchmarkCategory.CRYPTO),
    ("crypto-rsa-small", "RSA小さいn", BenchmarkCategory.CRYPTO),
    ("crypto-rsa-missing", "RSAパラメータ不足", BenchmarkCategory.CRYPTO),
    ("crypto-english", "誤解決しやすい通常英文", BenchmarkCategory.CRYPTO),
    ("rev-pe32", "PE32 x86", BenchmarkCategory.REV),
    ("rev-pe64", "PE32+ x86-64", BenchmarkCategory.REV),
    ("rev-elf32", "ELF32", BenchmarkCategory.REV),
    ("rev-elf64", "ELF64", BenchmarkCategory.REV),
    ("rev-strcmp", "strcmp手掛かり", BenchmarkCategory.REV),
    ("rev-ptrace", "ptrace手掛かり", BenchmarkCategory.REV),
    ("rev-broken-pe", "壊れたPE", BenchmarkCategory.REV),
    ("rev-broken-elf", "壊れたELF", BenchmarkCategory.REV),
    ("rev-overlay", "PE Overlay", BenchmarkCategory.REV),
    ("rev-embedded-flag", "実行ファイル内Flag候補", BenchmarkCategory.REV),
    ("forensics-png", "PNG metadata", BenchmarkCategory.FORENSICS),
    ("forensics-jpeg", "JPEG metadata", BenchmarkCategory.FORENSICS),
    ("forensics-zip", "ZIP内部Flag", BenchmarkCategory.FORENSICS),
    ("forensics-png-zip", "PNG末尾ZIP", BenchmarkCategory.FORENSICS),
    ("forensics-elf-tail", "ELF末尾追加データ", BenchmarkCategory.FORENSICS),
    ("forensics-unknown", "不明形式", BenchmarkCategory.FORENSICS),
    ("forensics-empty", "0 byte file", BenchmarkCategory.FORENSICS),
    ("forensics-mismatch", "拡張子と実形式不一致", BenchmarkCategory.FORENSICS),
    ("forensics-multiple", "複数ファイル", BenchmarkCategory.FORENSICS),
    ("forensics-broken-zip", "壊れたZIP", BenchmarkCategory.FORENSICS),
    ("web-http", "HTTP request text", BenchmarkCategory.WEB),
    ("web-sqli", "SQL Injection候補", BenchmarkCategory.WEB),
    ("web-cookie", "Cookieマスク確認", BenchmarkCategory.WEB),
    ("web-flag", "Web添付Flag", BenchmarkCategory.WEB),
    ("web-agent", "Agent fallback", BenchmarkCategory.WEB),
    ("safety-code", "AI回答コードなし", BenchmarkCategory.SAFETY),
    ("safety-policy", "外部Tool Policy拒否", BenchmarkCategory.SAFETY),
    ("integration-budget", "Budget拒否", BenchmarkCategory.INTEGRATION),
    ("integration-source", "未知source_index", BenchmarkCategory.INTEGRATION),
    ("misc-unresolved", "通常未解決問題", BenchmarkCategory.MISC),
)


def _file(case_id: str) -> FileInput:
    content = f"fixed:{case_id}".encode()
    return FileInput(
        name=f"{case_id}.bin",
        path=Path(f"fixtures/{case_id}.bin"),
        size=len(content),
        extension=".bin",
        content=content,
    )


def _cases() -> tuple[BenchmarkCase, ...]:
    cases: list[BenchmarkCase] = []
    paths = tuple(BenchmarkExpectedPath)
    for index, (case_id, name, category) in enumerate(CASE_NAMES):
        path = paths[index % len(paths)]
        expected_flag = f"FLAG{{{case_id}}}" if path is BenchmarkExpectedPath.LOCAL_SOLUTION else None
        agent_types = (AgentType.WEB,) if path is BenchmarkExpectedPath.AGENT_SOLUTION else ()
        cases.append(
            BenchmarkCase(
                case_id=case_id,
                name=name,
                category=category,
                question=f"固定ベンチマーク問題: {name}",
                files=(_file(case_id),),
                expected_path=path,
                expected_flag=expected_flag,
                expected_agent_types=agent_types,
                expected_ai_calls=1 if path is BenchmarkExpectedPath.AI_FALLBACK else 0,
                expected_tool_calls=0,
                max_duration_seconds=3.0,
                notes="固定サンプル。実API・実Toolは使用しない。",
            )
        )
    return tuple(cases)


class DeterministicFakeExecutor:
    """Case metadataだけで決定的なFake結果を返し、外部処理を起動しない。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, case: BenchmarkCase) -> BenchmarkExecutionResult:
        self.calls.append(case.case_id)
        return BenchmarkExecutionResult(
            actual_path=case.expected_path,
            solved=case.expected_path in {
                BenchmarkExpectedPath.LOCAL_SOLUTION,
                BenchmarkExpectedPath.AGENT_SOLUTION,
            },
            actual_flag=case.expected_flag,
            ai_calls=case.expected_ai_calls or 0,
            agent_runs=1 if case.expected_path is BenchmarkExpectedPath.AGENT_SOLUTION else 0,
            external_tool_calls=0,
            agent_types=case.expected_agent_types,
        )


def _summary(**overrides: object) -> BenchmarkSummary:
    values: dict[str, object] = {
        "total_cases": 0,
        "passed_cases": 0,
        "failed_cases": 0,
        "error_cases": 0,
        "timed_out_cases": 0,
        "local_solution_cases": 0,
        "agent_solution_cases": 0,
        "ai_fallback_cases": 0,
        "unresolved_cases": 0,
        "safe_failure_cases": 0,
        "false_positive_cases": 0,
        "incorrect_flag_cases": 0,
        "total_ai_calls": 0,
        "total_agent_runs": 0,
        "total_external_tool_calls": 0,
        "average_duration_seconds": 0.0,
        "max_duration_seconds": 0.0,
        "p95_duration_seconds": 0.0,
        "reproducible": True,
        "deterministic": True,
    }
    values.update(overrides)
    return BenchmarkSummary(**values)  # type: ignore[arg-type]


def test_benchmark_enums_and_fixed_catalog_cover_required_categories():
    cases = _cases()
    assert len(cases) >= 30
    assert {case.category for case in cases} == set(BenchmarkCategory)
    assert {case.expected_path for case in cases} == set(BenchmarkExpectedPath)
    assert len({case.case_id for case in cases}) == len(cases)
    assert all(case.files[0].content.startswith(b"fixed:") for case in cases)


def test_dtos_are_frozen_and_slotted():
    case = _cases()[0]
    with pytest.raises(FrozenInstanceError):
        case.name = "changed"  # type: ignore[misc]
    assert not hasattr(case, "__dict__")
    execution = BenchmarkExecutionResult(BenchmarkExpectedPath.UNRESOLVED, False)
    assert not hasattr(execution, "__dict__")
    summary = _summary()
    run = BenchmarkRunResult((), summary)
    assert not hasattr(summary, "__dict__")
    assert not hasattr(run, "__dict__")


@pytest.mark.parametrize("value", [-1, True])
def test_case_rejects_invalid_expected_counts(value: int):
    with pytest.raises((TypeError, ValueError)):
        BenchmarkCase(
            case_id="invalid",
            name="invalid",
            category=BenchmarkCategory.MISC,
            question="q",
            files=(),
            expected_path=BenchmarkExpectedPath.UNRESOLVED,
            expected_ai_calls=value,
        )


def test_summary_rejects_inconsistent_counts():
    with pytest.raises(ValueError, match="Status counts"):
        _summary(total_cases=1)


def test_runner_rejects_duplicate_case_ids():
    case = _cases()[0]
    with pytest.raises(ValueError, match="unique"):
        CtfBenchmarkRunner(case_executor=DeterministicFakeExecutor()).run((case, case))


def test_full_fixed_benchmark_is_deterministic_and_uses_only_fakes():
    cases = _cases()
    fake = DeterministicFakeExecutor()
    result = CtfBenchmarkRunner(case_executor=fake).run(cases)
    summary = result.summary
    assert tuple(item.case_id for item in result.results) == tuple(
        case.case_id for case in cases
    )
    assert fake.calls == [case.case_id for case in cases] * 2
    assert summary.total_cases == len(cases)
    assert summary.passed_cases == len(cases)
    assert summary.error_cases == 0
    assert summary.timed_out_cases == 0
    assert summary.false_positive_cases == 0
    assert summary.incorrect_flag_cases == 0
    assert summary.reproducible is True
    assert summary.deterministic is True
    assert summary.total_external_tool_calls == 0
    assert all(item.duration_seconds >= 0 for item in result.results)
    assert all(item.fingerprint for item in result.results)


def test_empty_benchmark_has_zero_metrics():
    result = CtfBenchmarkRunner(case_executor=DeterministicFakeExecutor()).run(())
    assert result.results == ()
    assert result.summary.total_cases == 0
    assert result.summary.average_duration_seconds == 0.0
    assert result.summary.max_duration_seconds == 0.0
    assert result.summary.p95_duration_seconds == 0.0


def test_exception_is_isolated_and_next_case_runs_without_message_leak():
    first, second = _cases()[:2]

    def execute(case: BenchmarkCase) -> BenchmarkExecutionResult:
        if case.case_id == first.case_id:
            raise RuntimeError("SECRET_API_KEY=do-not-store")
        return DeterministicFakeExecutor()(case)

    result = CtfBenchmarkRunner(case_executor=execute).run((first, second))
    assert result.results[0].status is BenchmarkCaseStatus.ERROR
    assert result.results[0].exception_type == "RuntimeError"
    assert "SECRET" not in repr(result.results[0])
    assert result.results[1].status is BenchmarkCaseStatus.PASSED


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit()])
def test_process_control_exceptions_propagate(error: BaseException):
    def execute(_case: BenchmarkCase) -> BenchmarkExecutionResult:
        raise error

    with pytest.raises(type(error)):
        CtfBenchmarkRunner(case_executor=execute).run((_cases()[0],))


def test_timeout_is_measured_without_forced_termination():
    ticks = iter((0.0, 2.0, 2.0, 4.0))
    case = _cases()[0]
    case = BenchmarkCase(
        case_id=case.case_id,
        name=case.name,
        category=case.category,
        question=case.question,
        files=case.files,
        expected_path=case.expected_path,
        expected_flag=case.expected_flag,
        expected_agent_types=case.expected_agent_types,
        expected_ai_calls=case.expected_ai_calls,
        expected_tool_calls=case.expected_tool_calls,
        max_duration_seconds=1.0,
    )
    result = CtfBenchmarkRunner(
        case_executor=DeterministicFakeExecutor(), clock=lambda: next(ticks)
    ).run((case,))
    assert result.results[0].status is BenchmarkCaseStatus.TIMED_OUT
    assert result.summary.timed_out_cases == 1


def test_wrong_path_flag_and_counts_are_reported_with_fixed_reasons():
    case = _cases()[0]

    def wrong(_case: BenchmarkCase) -> BenchmarkExecutionResult:
        return BenchmarkExecutionResult(
            actual_path=BenchmarkExpectedPath.AI_FALLBACK,
            solved=True,
            actual_flag="FLAG{wrong}",
            ai_calls=1,
            external_tool_calls=1,
        )

    result = CtfBenchmarkRunner(case_executor=wrong).run((case,)).results[0]
    assert result.status is BenchmarkCaseStatus.FAILED
    assert result.flag_correct is False
    assert result.false_positive is False
    assert "期待した解析経路と一致しません。" in result.failure_reasons
    assert "期待したFlagと一致しません。" in result.failure_reasons


def test_unexpected_confirmed_flag_is_false_positive_but_candidate_can_be_omitted():
    case = next(item for item in _cases() if item.expected_flag is None)

    def false_positive(_case: BenchmarkCase) -> BenchmarkExecutionResult:
        return BenchmarkExecutionResult(
            actual_path=case.expected_path,
            solved=False,
            actual_flag="FLAG{candidate_must_not_be_confirmed}",
            ai_calls=case.expected_ai_calls or 0,
            agent_runs=1 if case.expected_path is BenchmarkExpectedPath.AGENT_SOLUTION else 0,
            agent_types=case.expected_agent_types,
        )

    result = CtfBenchmarkRunner(case_executor=false_positive).run((case,))
    assert result.results[0].false_positive is True
    assert result.summary.false_positive_cases == 1


def test_duration_is_excluded_from_fingerprint_and_reproducibility():
    ticks = iter((0.0, 0.1, 10.0, 10.2))
    result = CtfBenchmarkRunner(
        case_executor=DeterministicFakeExecutor(), clock=lambda: next(ticks)
    ).run((_cases()[0],))
    assert result.summary.reproducible is True
    assert result.results[0].duration_seconds == pytest.approx(0.1)


def test_input_mutation_is_detected_and_makes_runs_non_deterministic():
    case = _cases()[0]

    def mutate(current: BenchmarkCase) -> BenchmarkExecutionResult:
        current.files[0].name = "mutated.bin"
        return DeterministicFakeExecutor()(current)

    result = CtfBenchmarkRunner(case_executor=mutate).run((case,))
    assert "入力DTOが変更されました。" in result.results[0].failure_reasons
    assert result.summary.deterministic is False


def test_case_result_validation_and_run_result_count_validation():
    with pytest.raises(ValueError, match="failure_reasons"):
        BenchmarkCaseResult(
            case_id="x",
            status=BenchmarkCaseStatus.FAILED,
            actual_path=BenchmarkExpectedPath.UNRESOLVED,
            solved=False,
            actual_flag=None,
            flag_correct=None,
            false_positive=False,
            ai_calls=0,
            agent_runs=0,
            external_tool_calls=0,
            duration_seconds=0.0,
            exception_type=None,
            failure_reasons=tuple("x" for _ in range(21)),
            fingerprint="fixed",
        )
    with pytest.raises(ValueError, match="Result count"):
        BenchmarkRunResult(results=(), summary=_summary(total_cases=1, passed_cases=1, unresolved_cases=1))
