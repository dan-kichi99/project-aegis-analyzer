from dataclasses import dataclass

MAX_PYTHON_SOURCE_CANDIDATES = 100
MAX_PYTHON_SOURCE_PREVIEW = 500


@dataclass(slots=True, frozen=True)
class PythonSourceCandidate:
    source: str
    method: str
    expression_type: str
    variable_name: str | None
    value_preview: str
    prefix: str | None
    body: str | None
    flag_candidate: str
    line_number: int | None
    confidence: int
    truncated: bool

    def __post_init__(self) -> None:
        if not self.source or len(self.source) > 500:
            raise ValueError("source must contain 1 to 500 characters.")
        if not self.flag_candidate:
            raise ValueError("flag_candidate must not be empty.")
        if len(self.value_preview) > MAX_PYTHON_SOURCE_PREVIEW:
            raise ValueError("value_preview must not exceed 500 characters.")
        if isinstance(self.confidence, bool) or not 0 <= self.confidence <= 100:
            raise ValueError("confidence must be from 0 to 100.")


@dataclass(slots=True, frozen=True)
class PythonSourceResult:
    candidates: tuple[PythonSourceCandidate, ...]
    truncated: bool

    def __post_init__(self) -> None:
        if len(self.candidates) > MAX_PYTHON_SOURCE_CANDIDATES:
            raise ValueError("candidates must not contain more than 100 items.")
        flags = [item.flag_candidate for item in self.candidates]
        if len(flags) != len(set(flags)):
            raise ValueError("flag candidates must not contain duplicates.")
