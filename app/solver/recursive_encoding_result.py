from dataclasses import dataclass

MAX_RECURSIVE_ENCODING_STEPS = 100
MAX_RECURSIVE_ENCODING_PREVIEW = 500


@dataclass(slots=True, frozen=True)
class RecursiveEncodingStep:
    method: str
    depth: int
    input_preview: str
    output_preview: str
    caesar_shift: int | None
    flag_candidate: str | None
    source: str
    truncated: bool

    def __post_init__(self) -> None:
        if not self.method or len(self.method) > 100:
            raise ValueError("method must contain 1 to 100 characters.")
        if isinstance(self.depth, bool) or not isinstance(self.depth, int):
            raise TypeError("depth must be an integer.")
        if self.depth < 0:
            raise ValueError("depth must be zero or greater.")
        if max(len(self.input_preview), len(self.output_preview)) > 500:
            raise ValueError("preview must not exceed 500 characters.")
        if self.caesar_shift is not None and not 1 <= self.caesar_shift <= 25:
            raise ValueError("caesar_shift must be from 1 to 25 or None.")
        if not self.source or len(self.source) > 500:
            raise ValueError("source must contain 1 to 500 characters.")


@dataclass(slots=True, frozen=True)
class RecursiveEncodingResult:
    steps: tuple[RecursiveEncodingStep, ...]
    flag_candidates: tuple[str, ...]
    truncated: bool

    def __post_init__(self) -> None:
        if len(self.steps) > MAX_RECURSIVE_ENCODING_STEPS:
            raise ValueError("steps must not contain more than 100 items.")
        if len(self.flag_candidates) != len(set(self.flag_candidates)):
            raise ValueError("flag_candidates must not contain duplicates.")
