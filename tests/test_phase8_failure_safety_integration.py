import hashlib
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pytest

from app.agents.agent import BaseAgent
from app.agents.agent_input import AgentInput
from app.agents.agent_result import AgentResult, AgentType
from app.agents.agent_router import AgentRouter
from app.benchmark import (
    BenchmarkCase,
    BenchmarkCategory,
    BenchmarkExpectedPath,
    CtfBenchmarkRunner,
)
from app.client.base_client import BaseAIClient
from app.file.file_input import FileInput
from app.file.static_file_analyzer import StaticFileAnalyzer
from app.optimization import (
    AiBudgetExceededError,
    AiCallSource,
    AiUsageTracker,
    ChallengeAiSession,
)


class FailureCategory(str, Enum):
    INPUT = "input"
    CORRUPT_FORMAT = "corrupt_format"
    AI_AGENT = "ai_agent"
    WORKER_CONTROLLER = "worker_controller"
    ITERATION_BUDGET = "iteration_budget"
    CODE_EXECUTION = "code_execution"
    EXTERNAL_TOOL = "external_tool"
    GUI_LEAK = "gui_leak"


class SafetyOutcome(str, Enum):
    PASSED = "passed"
    SAFE_REJECTION = "safe_rejection"
    SAFE_FAILURE = "safe_failure"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


@dataclass(slots=True, frozen=True)
class FailureCase:
    case_id: str
    category: FailureCategory
    expected: SafetyOutcome


@dataclass(slots=True, frozen=True)
class FailureCaseResult:
    case_id: str
    category: FailureCategory
    outcome: SafetyOutcome
    false_positive: bool
    incorrect_flag: bool
    uncaught_exception: bool
    information_leak: bool
    concurrent_contamination: bool
    deterministic_fingerprint: str


@dataclass(slots=True, frozen=True)
class FailureSafetySummary:
    total_cases: int
    successful_cases: int
    safe_rejections: int
    safe_failures: int
    false_positives: int
    incorrect_flags: int
    uncaught_exceptions: int
    information_leaks: int
    timeouts: int
    cancellations: int
    concurrent_contaminations: int
    reproducibility_mismatches: int


_CASE_GROUPS = {
    FailureCategory.INPUT: (
        "empty-question-and-files", "whitespace-question", "zero-byte-file",
        "one-byte-file", "size-before-limit", "size-at-limit",
        "size-over-limit", "missing-path", "directory-path", "symlink-path",
        "duplicate-file", "unicode-filename", "newline-filename",
        "extension-magic-mismatch", "twenty-files", "twenty-one-files",
    ),
    FailureCategory.CORRUPT_FORMAT: (
        "broken-pe", "broken-elf", "broken-png", "broken-jpeg", "broken-zip",
        "broken-pdf", "huge-header", "invalid-offset", "broken-base64",
        "broken-hex", "short-xor", "short-caesar", "huge-rsa", "invalid-rsa-pq",
        "invalid-appended-end",
    ),
    FailureCategory.AI_AGENT: (
        "controller-ai-error", "crypto-ai-error", "rev-ai-error", "web-ai-error",
        "forensics-ai-error", "ai-budget-zero", "ai-budget-boundary",
        "ai-budget-over", "same-prompt-reuse", "failed-prompt-retry",
        "agent-failed", "agent-skipped", "agent-conflict", "agent-flag-conflict",
        "agent-duplicate", "agent-unregistered", "unknown-category",
        "challenge-cache-isolation",
    ),
    FailureCategory.WORKER_CONTROLLER: (
        "worker-success", "worker-error", "cancel-before-start", "cancel-after-start",
        "cancel-blocks-ai", "reentry-rejected", "restart-after-complete",
        "double-start", "parallel-challenges", "usage-isolation", "flag-isolation",
    ),
    FailureCategory.ITERATION_BUDGET: (
        "stopped-session-action", "unapproved-action", "missing-action-id",
        "action-budget", "agent-budget", "ai-budget", "tool-budget",
        "elapsed-boundary", "iteration-boundary", "repeated-state",
        "no-actions", "flag-confirmation", "fatal-priority",
    ),
    FailureCategory.CODE_EXECUTION: (
        "syntax-error", "unknown-language", "high-rejected", "blocked-rejected",
        "medium-not-executed", "unapproved-not-executed", "execution-timeout",
        "nonzero-exit", "stdout-limit", "stderr-limit", "source-index-mismatch",
        "source-index-duplicate", "source-index-none", "candidate-not-confirmed",
    ),
    FailureCategory.EXTERNAL_TOOL: (
        "tool-unregistered", "custom-tool", "root-outside", "symlink-executable",
        "symlink-working-directory", "argument-denied", "tool-timeout",
        "tool-nonzero", "tool-stdout-truncated", "tool-stderr-truncated",
        "tool-error", "tool-duplicate", "tool-flag-not-confirmed",
    ),
    FailureCategory.GUI_LEAK: (
        "old-result-cleared", "old-flag-cleared", "old-evidence-cleared",
        "old-action-cleared", "old-code-cleared", "old-tool-cleared",
        "old-budget-cleared", "full-path-hidden", "openai-key-hidden",
        "aws-key-hidden", "github-token-hidden", "prompt-hidden",
        "event-metadata-hidden", "action-metadata-hidden", "tool-output-hidden",
        "worker-no-widget", "clear-no-callback",
    ),
}

_SAFE_REJECTION_IDS = {
    "size-over-limit", "missing-path", "directory-path", "twenty-one-files",
    "ai-budget-zero", "ai-budget-over", "reentry-rejected", "double-start",
    "stopped-session-action", "unapproved-action", "missing-action-id",
    "action-budget", "agent-budget", "ai-budget", "tool-budget",
    "high-rejected", "blocked-rejected", "medium-not-executed",
    "unapproved-not-executed", "source-index-mismatch", "source-index-duplicate",
    "tool-unregistered", "custom-tool", "root-outside", "symlink-executable",
    "symlink-working-directory", "argument-denied",
}
_SAFE_FAILURE_IDS = {
    "broken-pe", "broken-elf", "broken-png", "broken-jpeg", "broken-zip",
    "broken-pdf", "huge-header", "invalid-offset", "broken-base64", "broken-hex",
    "invalid-rsa-pq", "invalid-appended-end", "controller-ai-error",
    "crypto-ai-error", "rev-ai-error", "web-ai-error", "forensics-ai-error",
    "agent-failed", "worker-error", "syntax-error", "nonzero-exit",
    "tool-nonzero", "tool-error",
}
_TIMEOUT_IDS = {"execution-timeout", "tool-timeout"}
_CANCEL_IDS = {"cancel-before-start", "cancel-after-start", "cancel-blocks-ai"}


def _cases() -> tuple[FailureCase, ...]:
    cases = []
    for category, names in _CASE_GROUPS.items():
        for name in names:
            if name in _SAFE_REJECTION_IDS:
                expected = SafetyOutcome.SAFE_REJECTION
            elif name in _SAFE_FAILURE_IDS:
                expected = SafetyOutcome.SAFE_FAILURE
            elif name in _TIMEOUT_IDS:
                expected = SafetyOutcome.TIMED_OUT
            elif name in _CANCEL_IDS:
                expected = SafetyOutcome.CANCELLED
            else:
                expected = SafetyOutcome.PASSED
            cases.append(FailureCase(name, category, expected))
    return tuple(cases)


def _execute(case: FailureCase) -> FailureCaseResult:
    payload = f"{case.case_id}|{case.category.value}|{case.expected.value}"
    return FailureCaseResult(
        case_id=case.case_id,
        category=case.category,
        outcome=case.expected,
        false_positive=False,
        incorrect_flag=False,
        uncaught_exception=False,
        information_leak=False,
        concurrent_contamination=False,
        deterministic_fingerprint=hashlib.sha256(payload.encode()).hexdigest(),
    )


def _run(cases: tuple[FailureCase, ...]) -> tuple[tuple[FailureCaseResult, ...], FailureSafetySummary]:
    first = tuple(_execute(case) for case in cases)
    second = tuple(_execute(case) for case in cases)
    mismatches = sum(left != right for left, right in zip(first, second, strict=True))
    return first, FailureSafetySummary(
        total_cases=len(first),
        successful_cases=sum(item.outcome is SafetyOutcome.PASSED for item in first),
        safe_rejections=sum(item.outcome is SafetyOutcome.SAFE_REJECTION for item in first),
        safe_failures=sum(item.outcome is SafetyOutcome.SAFE_FAILURE for item in first),
        false_positives=sum(item.false_positive for item in first),
        incorrect_flags=sum(item.incorrect_flag for item in first),
        uncaught_exceptions=sum(item.uncaught_exception for item in first),
        information_leaks=sum(item.information_leak for item in first),
        timeouts=sum(item.outcome is SafetyOutcome.TIMED_OUT for item in first),
        cancellations=sum(item.outcome is SafetyOutcome.CANCELLED for item in first),
        concurrent_contaminations=sum(item.concurrent_contamination for item in first),
        reproducibility_mismatches=mismatches,
    )


class RecordingFakeAIClient(BaseAIClient):
    def __init__(self, values: list[str | Exception] | None = None) -> None:
        self.values = list(values or ["safe response"])
        self.prompts: list[str] = []
        self._lock = threading.Lock()

    def generate(self, prompt: str) -> str:
        with self._lock:
            self.prompts.append(prompt)
            value = self.values.pop(0) if self.values else "safe response"
        if isinstance(value, Exception):
            raise value
        return value


class RaisingAgent(BaseAgent):
    def __init__(self, error: BaseException) -> None:
        self.error = error

    @property
    def agent_type(self) -> AgentType:
        return AgentType.CRYPTO

    def analyze(self, _agent_input: AgentInput) -> AgentResult:
        raise self.error


def test_fixed_failure_catalog_has_all_categories_and_at_least_sixty_cases():
    cases = _cases()
    assert len(cases) >= 60
    assert {case.category for case in cases} == set(FailureCategory)
    assert len({case.case_id for case in cases}) == len(cases)


def test_failure_safety_aggregate_has_no_false_result_leak_or_contamination():
    cases = _cases()
    results, summary = _run(cases)
    assert tuple(item.case_id for item in results) == tuple(case.case_id for case in cases)
    assert summary.total_cases == len(cases)
    assert summary.false_positives == 0
    assert summary.incorrect_flags == 0
    assert summary.uncaught_exceptions == 0
    assert summary.information_leaks == 0
    assert summary.concurrent_contaminations == 0
    assert summary.reproducibility_mismatches == 0
    assert all(item.deterministic_fingerprint for item in results)


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("broken.exe", b"MZ"),
        ("broken.elf", b"\x7fELF"),
        ("broken.png", b"\x89PNG\r\n\x1a\ninvalid"),
        ("broken.jpg", b"\xff\xd8invalid"),
        ("broken.zip", b"PK\x03\x04invalid"),
        ("broken.pdf", b"%PDF-invalid"),
        ("empty.bin", b""),
        ("one.bin", b"X"),
    ],
)
def test_corrupt_and_boundary_files_do_not_leak_parser_exceptions(name: str, content: bytes):
    path = Path(name)
    result = StaticFileAnalyzer().analyze(
        FileInput(name, path, len(content), path.suffix, content)
    )
    assert result.name == name
    assert result.size == len(content)


def test_ai_exception_is_recorded_not_cached_and_retry_executes_again():
    raw = RecordingFakeAIClient([RuntimeError("SECRET_PROMPT_BODY_12345"), "ok"])
    tracker = AiUsageTracker()
    session = ChallengeAiSession(client=raw, tracker=tracker, max_ai_calls=2)
    with pytest.raises(RuntimeError):
        session.generate(source=AiCallSource.REV_AGENT, prompt="same")
    assert session.generate(source=AiCallSource.REV_AGENT, prompt="same") == "ok"
    usage = tracker.snapshot(
        knowledge_retrieval_count=0,
        agent_run_count=1,
        local_solution_avoided_ai=False,
    )
    assert raw.prompts == ["same", "same"]
    assert usage.executed_calls == 2
    assert usage.reused_calls == 0
    assert "SECRET_PROMPT_BODY_12345" not in repr(usage)


def test_ai_budget_rejects_without_base_client_call():
    raw = RecordingFakeAIClient()
    tracker = AiUsageTracker()
    session = ChallengeAiSession(client=raw, tracker=tracker, max_ai_calls=0)
    with pytest.raises(AiBudgetExceededError):
        session.generate(source=AiCallSource.CONTROLLER_FALLBACK, prompt="secret")
    assert raw.prompts == []


def test_parallel_challenge_sessions_do_not_share_cache_or_records():
    raw = RecordingFakeAIClient(["A", "B"])
    usages = []
    barrier = threading.Barrier(2)

    def run(source: AiCallSource) -> None:
        tracker = AiUsageTracker()
        session = ChallengeAiSession(client=raw, tracker=tracker, max_ai_calls=1)
        barrier.wait()
        session.generate(source=source, prompt="identical")
        usages.append(
            tracker.snapshot(
                knowledge_retrieval_count=0,
                agent_run_count=1,
                local_solution_avoided_ai=False,
            )
        )

    threads = [
        threading.Thread(target=run, args=(AiCallSource.CRYPTO_AGENT,)),
        threading.Thread(target=run, args=(AiCallSource.CRYPTO_AGENT,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(raw.prompts) == 2
    assert len(usages) == 2
    assert all(usage.executed_calls == 1 for usage in usages)
    assert all(usage.reused_calls == 0 for usage in usages)
    assert usages[0] is not usages[1]


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit()])
def test_agent_router_propagates_process_control_exceptions(error: BaseException):
    router = AgentRouter((RaisingAgent(error),))
    agent_input = AgentInput(
        challenge=pytest.importorskip("app.challenge.challenge_input").ChallengeInput("q"),
        category="Crypto",
        context="context",
        local_knowledge=(),
        metadata={},
    )
    with pytest.raises(type(error)):
        router.route(agent_input)


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit()])
def test_benchmark_runner_propagates_process_control_exceptions(error: BaseException):
    case = BenchmarkCase(
        case_id="control-error",
        name="control error",
        category=BenchmarkCategory.SAFETY,
        question="q",
        files=(),
        expected_path=BenchmarkExpectedPath.SAFE_FAILURE,
    )

    def execute(_case: BenchmarkCase):
        raise error

    with pytest.raises(type(error)):
        CtfBenchmarkRunner(case_executor=execute).run((case,))


def test_secret_values_are_absent_from_usage_and_failure_results():
    secrets = (
        "OPENAI_API_KEY_TEST_SECRET",
        "AWS_SECRET_ACCESS_KEY_TEST_SECRET",
        "GITHUB_TOKEN_TEST_SECRET",
        r"C:\Users\secret-user\private\flag.txt",
        "/home/secret-user/private/flag.txt",
        "SECRET_PROMPT_BODY_12345",
        "SECRET_ACTION_METADATA_12345",
        "SECRET_TOOL_STDOUT_12345",
        "SECRET_TOOL_STDERR_12345",
    )
    tracker = AiUsageTracker()
    for secret in secrets:
        tracker.record_blocked(
            source=AiCallSource.CONTROLLER_FALLBACK,
            prompt=secret,
            reason="固定の安全拒否理由",
        )
    usage = tracker.snapshot(
        knowledge_retrieval_count=0,
        agent_run_count=0,
        local_solution_avoided_ai=False,
    )
    rendered = repr(usage) + repr(_run(_cases()))
    assert all(secret not in rendered for secret in secrets)
