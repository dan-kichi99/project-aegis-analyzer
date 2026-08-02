from dataclasses import dataclass
from enum import Enum
from math import isfinite
from pathlib import Path

from app.external_tools.process_request import (
    MAX_PROCESS_ARGUMENT_CHARACTERS,
    MAX_PROCESS_ARGUMENTS,
    MAX_PROCESS_TIMEOUT_SECONDS,
    MAX_STDERR_BYTES,
    MAX_STDOUT_BYTES,
    ExternalProcessRequest,
)
from app.external_tools.tool import ExternalToolType

MAX_POLICY_MESSAGE_CHARACTERS = 500


class ToolArgumentKind(str, Enum):
    EXACT = "exact"
    PREFIX = "prefix"
    PATH_WITHIN_WORKING_DIRECTORY = "path_within_working_directory"


@dataclass(slots=True, frozen=True)
class ToolArgumentRule:
    kind: ToolArgumentKind
    value: str | None

    def __post_init__(self) -> None:
        if self.kind is ToolArgumentKind.PATH_WITHIN_WORKING_DIRECTORY:
            if self.value is not None:
                raise ValueError("Path RuleのvalueはNoneで指定してください。")
            return
        if not isinstance(self.value, str) or not self.value:
            raise ValueError("EXACT/PREFIX Ruleには空でないvalueが必要です。")
        if "\0" in self.value:
            raise ValueError("Rule valueにNUL文字を含めることはできません。")


@dataclass(slots=True, frozen=True)
class AllowedTool:
    tool_type: ExternalToolType
    executable: Path
    allowed_argument_prefixes: tuple[str, ...]
    allowed_exact_arguments: tuple[str, ...]
    max_arguments: int
    timeout_seconds: float
    max_stdout_bytes: int
    max_stderr_bytes: int
    argument_rules: tuple[ToolArgumentRule, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.executable, Path) or not self.executable.is_absolute():
            raise ValueError("executableは絶対Pathで指定してください。")
        if not isinstance(self.allowed_argument_prefixes, tuple):
            raise ValueError(  # noqa: TRY004 - DTO入力違反はValueErrorへ統一
                "allowed_argument_prefixesはtupleで指定してください。"
            )
        if not isinstance(self.allowed_exact_arguments, tuple):
            raise ValueError(  # noqa: TRY004 - DTO入力違反はValueErrorへ統一
                "allowed_exact_argumentsはtupleで指定してください。"
            )
        if not isinstance(self.argument_rules, tuple):
            raise ValueError(  # noqa: TRY004 - DTO入力違反はValueErrorへ統一
                "argument_rulesはtupleで指定してください。"
            )
        self._validate_values(self.allowed_argument_prefixes, "prefix", False)
        self._validate_values(self.allowed_exact_arguments, "exact", True)
        if (
            not isinstance(self.max_arguments, int)
            or isinstance(self.max_arguments, bool)
            or not 0 <= self.max_arguments <= MAX_PROCESS_ARGUMENTS
        ):
            raise ValueError("max_argumentsは0から50で指定してください。")
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or not isfinite(self.timeout_seconds)
            or not 0 < self.timeout_seconds <= MAX_PROCESS_TIMEOUT_SECONDS
        ):
            raise ValueError("timeout_secondsは0より大きく10以下で指定してください。")
        self._validate_limit(self.max_stdout_bytes, MAX_STDOUT_BYTES, "max_stdout_bytes")
        self._validate_limit(self.max_stderr_bytes, MAX_STDERR_BYTES, "max_stderr_bytes")

    def _validate_values(
        self, values: tuple[str, ...], name: str, allow_empty: bool
    ) -> None:
        for value in values:
            if not isinstance(value, str):
                raise ValueError(  # noqa: TRY004 - DTO入力違反はValueErrorへ統一
                    f"{name}は文字列で指定してください。"
                )
            if not allow_empty and not value:
                raise ValueError("空prefixは指定できません。")
            if "\0" in value:
                raise ValueError(f"{name}にNUL文字を含めることはできません。")

    def _validate_limit(self, value: int, maximum: int, name: str) -> None:
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 1 <= value <= maximum
        ):
            raise ValueError(f"{name}は1から{maximum}で指定してください。")


@dataclass(slots=True, frozen=True)
class ExternalToolInvocation:
    tool_type: ExternalToolType
    arguments: tuple[str, ...]
    working_directory: Path

    def __post_init__(self) -> None:
        if not isinstance(self.arguments, tuple):
            raise ValueError(  # noqa: TRY004 - DTO入力違反はValueErrorへ統一
                "argumentsはtupleで指定してください。"
            )
        if len(self.arguments) > MAX_PROCESS_ARGUMENTS:
            raise ValueError("argumentsは最大50件です。")
        for argument in self.arguments:
            if not isinstance(argument, str):
                raise ValueError(  # noqa: TRY004 - DTO入力違反はValueErrorへ統一
                    "引数は文字列で指定してください。"
                )
            if len(argument) > MAX_PROCESS_ARGUMENT_CHARACTERS:
                raise ValueError("1引数は4096文字以内で指定してください。")
            if "\0" in argument:
                raise ValueError("引数にNUL文字を含めることはできません。")
        if (
            not isinstance(self.working_directory, Path)
            or not self.working_directory.is_absolute()
        ):
            raise ValueError("working_directoryは絶対Pathで指定してください。")


class ToolPolicyDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


class ToolPolicyDenialReason(str, Enum):
    CUSTOM_TOOL_NOT_ALLOWED = "custom_tool_not_allowed"
    TOOL_NOT_REGISTERED = "tool_not_registered"
    EXECUTABLE_INVALID = "executable_invalid"
    WORKING_DIRECTORY_INVALID = "working_directory_invalid"
    WORKING_DIRECTORY_OUTSIDE_ROOT = "working_directory_outside_root"
    TOO_MANY_ARGUMENTS = "too_many_arguments"
    ARGUMENT_TOO_LONG = "argument_too_long"
    INVALID_ARGUMENT = "invalid_argument"
    ARGUMENT_NOT_ALLOWED = "argument_not_allowed"


@dataclass(slots=True, frozen=True)
class ToolPolicyEvaluation:
    decision: ToolPolicyDecision
    allowed: bool
    primary_reason: ToolPolicyDenialReason | None
    matched_reasons: tuple[ToolPolicyDenialReason, ...]
    message: str
    process_request: ExternalProcessRequest | None

    def __post_init__(self) -> None:
        if len(self.message) > MAX_POLICY_MESSAGE_CHARACTERS:
            raise ValueError("messageは500文字以内で指定してください。")
        if self.decision is ToolPolicyDecision.ALLOW:
            if not self.allowed or self.primary_reason is not None:
                raise ValueError("ALLOWではallowed=True、primary_reason=Noneが必要です。")
            if self.process_request is None:
                raise ValueError("ALLOWではprocess_requestが必要です。")
        elif self.allowed or self.primary_reason is None:
            raise ValueError("DENYではallowed=False、primary_reasonが必要です。")
        if self.primary_reason is not None and (
            not self.matched_reasons
            or self.matched_reasons[0] is not self.primary_reason
        ):
            raise ValueError("primary_reasonはmatched_reasonsの先頭にしてください。")
        if self.decision is ToolPolicyDecision.DENY and self.process_request is not None:
            raise ValueError("DENYではprocess_requestを指定できません。")
