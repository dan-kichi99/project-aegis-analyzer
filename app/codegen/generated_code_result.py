from dataclasses import dataclass
from enum import Enum

from app.codegen.code_safety_result import CodeSafetyResult


class GeneratedCodeLanguage(str, Enum):
    PYTHON = "python"
    UNKNOWN = "unknown"


class GeneratedCodeStatus(str, Enum):
    PROPOSED = "proposed"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(slots=True, frozen=True)
class GeneratedCode:
    language: GeneratedCodeLanguage
    code: str
    purpose: str | None
    source_index: int
    status: GeneratedCodeStatus
    safety: CodeSafetyResult | None = None


@dataclass(slots=True, frozen=True)
class GeneratedCodeResult:
    items: tuple[GeneratedCode, ...]
