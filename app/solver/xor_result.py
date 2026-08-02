from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class XorCandidate:
    key: int
    plaintext: str
    score: float
    contains_flag: bool
    source: str


@dataclass(slots=True, frozen=True)
class SingleByteXorResult:
    candidates: tuple[XorCandidate, ...]
