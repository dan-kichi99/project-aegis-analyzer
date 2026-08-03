from dataclasses import dataclass

MAX_JAVA_SOURCE_CANDIDATES = 100
MAX_JAVA_SOURCE_PREVIEW = 500


@dataclass(slots=True, frozen=True)
class JavaSourceCandidate:
    source: str
    prefix: str | None
    body: str
    flag_candidate: str | None
    method: str
    confidence: int
    line_number: int | None
    evidence_preview: str
    truncated: bool

    def __post_init__(self) -> None:
        if not self.source or len(self.source) > 500:
            raise ValueError("source must contain 1 to 500 characters.")
        if not self.body:
            raise ValueError("body must not be empty.")
        if self.method not in {
            "java_equals",
            "java_equals_ignore_case",
            "java_string_builder_reverse",
            "java_char_array",
            "java_byte_array",
        }:
            raise ValueError("unsupported Java extraction method.")
        if isinstance(self.confidence, bool) or not 0 <= self.confidence <= 100:
            raise ValueError("confidence must be from 0 to 100.")
        if self.line_number is not None and self.line_number < 1:
            raise ValueError("line_number must be positive or None.")
        if len(self.evidence_preview) > MAX_JAVA_SOURCE_PREVIEW:
            raise ValueError("evidence_preview must not exceed 500 characters.")


@dataclass(slots=True, frozen=True)
class JavaSourceResult:
    candidates: tuple[JavaSourceCandidate, ...]
    truncated: bool

    def __post_init__(self) -> None:
        if len(self.candidates) > MAX_JAVA_SOURCE_CANDIDATES:
            raise ValueError("candidates must not contain more than 100 items.")
        keys = [(item.method, item.body, item.prefix) for item in self.candidates]
        if len(keys) != len(set(keys)):
            raise ValueError("candidates must not contain duplicates.")
