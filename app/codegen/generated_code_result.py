from dataclasses import dataclass
from enum import Enum


class GeneratedCodeLanguage(str, Enum):
    PYTHON = "python"
    UNKNOWN = "unknown"


class GeneratedCodeStatus(str, Enum):
    PROPOSED = "proposed"
    REVIEW_REQUIRED = "review_required"


@dataclass(slots=True, frozen=True)
class GeneratedCode:
    language: GeneratedCodeLanguage
    code: str
    purpose: str | None
    source_index: int
    status: GeneratedCodeStatus


@dataclass(slots=True, frozen=True)
class GeneratedCodeResult:
    items: tuple[GeneratedCode, ...]
