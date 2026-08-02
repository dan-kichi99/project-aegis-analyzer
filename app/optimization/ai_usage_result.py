import re
from dataclasses import dataclass
from enum import Enum

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
MAX_AI_USAGE_RECORDS = 100
MAX_BLOCK_REASON_CHARACTERS = 500


class AiCallSource(str, Enum):
    CONTROLLER_FALLBACK = "controller_fallback"
    CRYPTO_AGENT = "crypto_agent"
    REV_AGENT = "rev_agent"
    WEB_AGENT = "web_agent"
    FORENSICS_AGENT = "forensics_agent"


def _count(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer.")
    if value < 0:
        raise ValueError(f"{name} must be zero or greater.")


@dataclass(slots=True, frozen=True)
class AiCallRecord:
    sequence: int
    source: AiCallSource
    prompt_length: int
    prompt_fingerprint: str
    executed: bool
    reused: bool
    blocked: bool
    block_reason: str | None
    response_length: int | None
    succeeded: bool | None

    def __post_init__(self) -> None:
        _count(self.sequence, "sequence")
        _count(self.prompt_length, "prompt_length")
        if not isinstance(self.source, AiCallSource):
            raise TypeError("source must be AiCallSource.")
        if not all(isinstance(value, bool) for value in (self.executed, self.reused, self.blocked)):
            raise TypeError("Call state fields must be booleans.")
        if self.succeeded is not None and not isinstance(self.succeeded, bool):
            raise TypeError("succeeded must be a boolean or None.")
        if not _SHA256_PATTERN.fullmatch(self.prompt_fingerprint):
            raise ValueError("prompt_fingerprint must be a SHA-256 hexadecimal value.")
        if len(self.block_reason or "") > MAX_BLOCK_REASON_CHARACTERS:
            raise ValueError("block_reason must not exceed 500 characters.")
        modes = sum((self.executed, self.reused, self.blocked))
        if modes != 1:
            raise ValueError("Exactly one call state must be true.")
        if self.executed:
            if self.succeeded is None:
                raise ValueError("An executed call must declare whether it succeeded.")
            if self.block_reason is not None:
                raise ValueError("An executed call cannot have a block_reason.")
        elif self.succeeded is not None:
            raise ValueError("A non-executed call cannot have a success state.")
        if self.blocked != (self.block_reason is not None):
            raise ValueError("Only a blocked call may have a block_reason.")
        if self.response_length is not None:
            _count(self.response_length, "response_length")
            if not self.executed or self.succeeded is not True:
                raise ValueError("response_length is only valid for a successful call.")
        elif self.executed and self.succeeded:
            raise ValueError("A successful call must have response_length.")


@dataclass(slots=True, frozen=True)
class ChallengeAiUsage:
    records: tuple[AiCallRecord, ...]
    attempted_calls: int
    executed_calls: int
    reused_calls: int
    blocked_calls: int
    total_prompt_characters: int
    total_response_characters: int
    unique_prompt_count: int
    duplicate_prompt_count: int
    knowledge_retrieval_count: int
    agent_run_count: int
    local_solution_avoided_ai: bool

    def __post_init__(self) -> None:
        if len(self.records) > MAX_AI_USAGE_RECORDS:
            raise ValueError("records must not contain more than 100 items.")
        names = (
            "attempted_calls",
            "executed_calls",
            "reused_calls",
            "blocked_calls",
            "total_prompt_characters",
            "total_response_characters",
            "unique_prompt_count",
            "duplicate_prompt_count",
            "knowledge_retrieval_count",
            "agent_run_count",
        )
        for name in names:
            _count(getattr(self, name), name)
        if not isinstance(self.local_solution_avoided_ai, bool):
            raise TypeError("local_solution_avoided_ai must be a boolean.")
        if self.attempted_calls != len(self.records):
            raise ValueError("attempted_calls must equal the record count.")
        if self.executed_calls != sum(record.executed for record in self.records):
            raise ValueError("executed_calls is inconsistent with records.")
        if self.reused_calls != sum(record.reused for record in self.records):
            raise ValueError("reused_calls is inconsistent with records.")
        if self.blocked_calls != sum(record.blocked for record in self.records):
            raise ValueError("blocked_calls is inconsistent with records.")
        if self.total_prompt_characters != sum(
            record.prompt_length for record in self.records
        ):
            raise ValueError("total_prompt_characters is inconsistent with records.")
        if self.total_response_characters != sum(
            record.response_length or 0 for record in self.records
        ):
            raise ValueError("total_response_characters is inconsistent with records.")
        fingerprints = {record.prompt_fingerprint for record in self.records}
        if self.unique_prompt_count != len(fingerprints):
            raise ValueError("unique_prompt_count is inconsistent with records.")
        if self.duplicate_prompt_count != len(self.records) - len(fingerprints):
            raise ValueError("duplicate_prompt_count is inconsistent with records.")
