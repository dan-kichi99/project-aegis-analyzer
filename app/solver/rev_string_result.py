from dataclasses import dataclass

MAX_REV_STRING_CANDIDATES = 100
MAX_REV_STRING_PREVIEW = 500


@dataclass(slots=True, frozen=True)
class RevStringCandidate:
    source: str
    method: str
    reconstructed: str
    flag_candidate: str
    used_strings: int
    reconstruction_path: tuple[str, ...]
    confidence: int
    preview: str
    truncated: bool

    def __post_init__(self) -> None:
        if not self.source or len(self.source) > 500:
            raise ValueError("source must contain 1 to 500 characters.")
        if not self.flag_candidate:
            raise ValueError("flag_candidate must not be empty.")
        if not 1 <= self.used_strings <= 8:
            raise ValueError("used_strings must be from 1 to 8.")
        if isinstance(self.confidence, bool) or not 0 <= self.confidence <= 100:
            raise ValueError("confidence must be from 0 to 100.")
        if len(self.preview) > MAX_REV_STRING_PREVIEW:
            raise ValueError("preview must not exceed 500 characters.")


@dataclass(slots=True, frozen=True)
class RevStringResult:
    candidates: tuple[RevStringCandidate, ...]
    truncated: bool

    def __post_init__(self) -> None:
        if len(self.candidates) > MAX_REV_STRING_CANDIDATES:
            raise ValueError("candidates must not contain more than 100 items.")
        flags = [item.flag_candidate for item in self.candidates]
        if len(flags) != len(set(flags)):
            raise ValueError("flag candidates must not contain duplicates.")
