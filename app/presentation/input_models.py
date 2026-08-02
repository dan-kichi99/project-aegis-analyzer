from dataclasses import dataclass
from enum import Enum
from pathlib import Path

MAX_QUESTION_CHARACTERS = 20_000
MAX_INPUT_FILES = 20
MAX_VALIDATION_ERRORS = 20


@dataclass(slots=True, frozen=True)
class AnalysisInputState:
    question: str
    file_paths: tuple[Path, ...]
    selected_index: int | None
    validation_errors: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.question) > MAX_QUESTION_CHARACTERS:
            raise ValueError("問題文は20,000文字以内で指定してください。")
        if len(self.file_paths) > MAX_INPUT_FILES:
            raise ValueError("添付ファイルは最大20件です。")
        if len(set(self.file_paths)) != len(self.file_paths):
            raise ValueError("添付ファイルに重複があります。")
        if len(self.validation_errors) > MAX_VALIDATION_ERRORS:
            raise ValueError("検証エラーは最大20件です。")
        if self.selected_index is not None and (
            not isinstance(self.selected_index, int)
            or isinstance(self.selected_index, bool)
            or not 0 <= self.selected_index < len(self.file_paths)
        ):
            raise ValueError("selected_indexが範囲外です。")


@dataclass(slots=True, frozen=True)
class AnalysisRequest:
    question: str
    file_paths: tuple[Path, ...]

    def __post_init__(self) -> None:
        if len(self.question) > MAX_QUESTION_CHARACTERS:
            raise ValueError("問題文は20,000文字以内で指定してください。")
        if len(self.file_paths) > MAX_INPUT_FILES:
            raise ValueError("添付ファイルは最大20件です。")
        if not self.question.strip() and not self.file_paths:
            raise ValueError("問題文または添付ファイルを指定してください。")
        for path in self.file_paths:
            if not isinstance(path, Path) or not path.is_absolute():
                raise ValueError("添付ファイルは絶対Pathで指定してください。")
            if path.is_symlink():
                raise ValueError("シンボリックリンクは指定できません。")
            if not path.exists():
                raise ValueError("添付ファイルが見つかりません。")
            if not path.is_file():
                raise ValueError("添付ファイルとして通常ファイルを指定してください。")


class InputValidationStatus(str, Enum):
    VALID = "valid"
    INVALID = "invalid"


@dataclass(slots=True, frozen=True)
class InputValidationResult:
    status: InputValidationStatus
    valid: bool
    errors: tuple[str, ...]
    request: AnalysisRequest | None

    def __post_init__(self) -> None:
        if self.status is InputValidationStatus.VALID:
            if not self.valid or self.errors or self.request is None:
                raise ValueError("VALIDの検証結果が不整合です。")
        elif self.valid or not self.errors or self.request is not None:
            raise ValueError("INVALIDの検証結果が不整合です。")
