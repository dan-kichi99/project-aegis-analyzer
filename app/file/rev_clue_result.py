from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class RevClue:
    value: str
    category: str
    description: str
    severity: str


@dataclass(slots=True, frozen=True)
class RevClueResult:
    clues: tuple[RevClue, ...]
