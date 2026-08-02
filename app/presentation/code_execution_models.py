from dataclasses import dataclass
from enum import Enum

MAX_CODE_CANDIDATES = 5
MAX_CODE_CHARACTERS = 20_000
MAX_CODE_FINDINGS = 100
MAX_EXECUTION_RESULTS = 5


class CodeApprovalDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    DEFER = "defer"


@dataclass(slots=True, frozen=True)
class CodeApprovalRequest:
    source_index: int
    decision: CodeApprovalDecision

    def __post_init__(self) -> None:
        _validate_source_index(self.source_index)
        if not isinstance(self.decision, CodeApprovalDecision):
            raise TypeError("decisionが不正です。")


@dataclass(slots=True, frozen=True)
class CodeExecutionRequest:
    source_index: int

    def __post_init__(self) -> None:
        _validate_source_index(self.source_index)


@dataclass(slots=True, frozen=True)
class CodeCandidateViewModel:
    source_index: int
    language: str
    purpose: str | None
    status: str
    code: str
    risk_level: str
    parseable: bool
    findings: tuple[str, ...]
    syntax_error: str | None
    can_approve: bool
    can_reject: bool
    can_defer: bool
    can_execute: bool

    def __post_init__(self) -> None:
        _validate_source_index(self.source_index)
        if len(self.code) > MAX_CODE_CHARACTERS:
            raise ValueError("codeは20000文字以内で指定してください。")
        if self.purpose is not None and len(self.purpose) > 300:
            raise ValueError("purposeは300文字以内で指定してください。")
        if len(self.findings) > MAX_CODE_FINDINGS or any(
            len(item) > 500 for item in self.findings
        ):
            raise ValueError("findingsが表示上限を超えています。")
        if self.syntax_error is not None and len(self.syntax_error) > 500:
            raise ValueError("syntax_errorは500文字以内で指定してください。")


@dataclass(slots=True, frozen=True)
class ExecutionResultViewModel:
    source_index: int
    status: str
    exit_code: int | None
    duration_seconds: float
    stdout: str
    stderr: str
    timed_out: bool
    output_truncated: bool
    cleanup_succeeded: bool
    flag_candidates: tuple[str, ...]
    primary_flag: str | None
    successful_execution: bool
    warning: str

    def __post_init__(self) -> None:
        _validate_source_index(self.source_index)
        if len(self.stdout) > 65_536 or len(self.stderr) > 65_536:
            raise ValueError("stdoutまたはstderrが表示上限を超えています。")
        if len(self.flag_candidates) > 100:
            raise ValueError("Flag候補が表示上限を超えています。")
        if len(self.warning) > 500:
            raise ValueError("warningは500文字以内で指定してください。")


@dataclass(slots=True, frozen=True)
class CodeExecutionState:
    candidates: tuple[CodeCandidateViewModel, ...]
    selected_index: int | None
    selected_candidate: CodeCandidateViewModel | None
    execution_results: tuple[ExecutionResultViewModel, ...]
    message: str

    def __post_init__(self) -> None:
        if len(self.candidates) > MAX_CODE_CANDIDATES:
            raise ValueError("candidatesは最大5件です。")
        if len(self.execution_results) > MAX_EXECUTION_RESULTS:
            raise ValueError("execution_resultsは最大5件です。")
        if len(self.message) > 500:
            raise ValueError("messageは500文字以内で指定してください。")
        if isinstance(self.selected_index, bool):
            raise TypeError("selected_indexにboolは指定できません。")
        if self.selected_index is None:
            if self.selected_candidate is not None:
                raise ValueError("未選択時にselected_candidateは指定できません。")
        elif not 0 <= self.selected_index < len(self.candidates):
            raise ValueError("selected_indexが範囲外です。")
        elif self.selected_candidate != self.candidates[self.selected_index]:
            raise ValueError("selected_indexとselected_candidateが一致しません。")


def _validate_source_index(value: int) -> None:
    if isinstance(value, bool):
        raise TypeError("source_indexにboolは指定できません。")
    if not isinstance(value, int):
        raise TypeError("source_indexは整数で指定してください。")
    if value < 0:
        raise ValueError("source_indexは0以上で指定してください。")
