from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class CaesarCandidate:
    shift: int
    plaintext: str
    score: float
    contains_flag: bool
    source: str


@dataclass(slots=True, frozen=True)
class CaesarResult:
    candidates: tuple[CaesarCandidate, ...]
