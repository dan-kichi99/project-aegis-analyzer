from dataclasses import dataclass

MAX_UNIVERSAL_ENCODING_PREVIEW = 500
MAX_UNIVERSAL_ENCODING_STEPS = 100


@dataclass(slots=True, frozen=True)
class UniversalEncodingStep:
    method: str
    depth: int
    source: str
    input_preview: str
    output_preview: str
    flag_candidate: str | None
    truncated: bool
    transformation_path: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.method or len(self.method) > 100:
            raise ValueError("method must contain 1 to 100 characters.")
        if isinstance(self.depth, bool) or not isinstance(self.depth, int):
            raise TypeError("depth must be an integer.")
        if not 1 <= self.depth <= 3:
            raise ValueError("depth must be from 1 to 3.")
        if not self.source or len(self.source) > 500:
            raise ValueError("source must contain 1 to 500 characters.")
        if max(len(self.input_preview), len(self.output_preview)) > 500:
            raise ValueError("preview must not exceed 500 characters.")
        if not self.transformation_path:
            raise ValueError("transformation_path must not be empty.")


@dataclass(slots=True, frozen=True)
class UniversalEncodingResult:
    steps: tuple[UniversalEncodingStep, ...]
    flag_candidates: tuple[str, ...]
    truncated: bool

    def __post_init__(self) -> None:
        if len(self.steps) > MAX_UNIVERSAL_ENCODING_STEPS:
            raise ValueError("steps must not contain more than 100 items.")
        if len(self.flag_candidates) > MAX_UNIVERSAL_ENCODING_STEPS:
            raise ValueError("flag_candidates must not contain more than 100 items.")
        if len(self.flag_candidates) != len(set(self.flag_candidates)):
            raise ValueError("flag_candidates must not contain duplicates.")
