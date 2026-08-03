from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class NewCaesarCandidate:
    """New Caesar（b16_encode＋16文字AlphabetのCaesar）の復号候補。"""

    key: int
    alphabet: str
    plaintext: str
    contains_flag: bool
    source: str


@dataclass(slots=True, frozen=True)
class NewCaesarResult:
    candidates: tuple[NewCaesarCandidate, ...]
