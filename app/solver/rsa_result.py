from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class RsaParameters:
    n: int | None = None
    e: int | None = None
    c: int | None = None
    p: int | None = None
    q: int | None = None
    d: int | None = None
    phi: int | None = None
    source: str = ""


@dataclass(slots=True, frozen=True)
class RsaAttempt:
    method: str
    success: bool
    detail: str
    plaintext: str | None
    contains_flag: bool


@dataclass(slots=True, frozen=True)
class RsaResult:
    parameters: RsaParameters
    attempts: tuple[RsaAttempt, ...]
    plaintext: str | None
    contains_flag: bool
