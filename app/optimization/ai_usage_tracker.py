import hashlib

from app.optimization.ai_usage_result import (
    MAX_AI_USAGE_RECORDS,
    AiCallRecord,
    AiCallSource,
    ChallengeAiUsage,
)


class AiUsageTracker:
    def __init__(self, max_records: int = MAX_AI_USAGE_RECORDS) -> None:
        if (
            isinstance(max_records, bool)
            or not isinstance(max_records, int)
            or not 1 <= max_records <= MAX_AI_USAGE_RECORDS
        ):
            raise ValueError("max_records must be an integer from 1 to 100.")
        self._max_records = max_records
        self._records: list[AiCallRecord] = []

    @property
    def executed_calls(self) -> int:
        return sum(record.executed for record in self._records)

    def record_executed(
        self, *, source: AiCallSource, prompt: str, response: str
    ) -> None:
        self._append(
            source=source,
            prompt=prompt,
            executed=True,
            response_length=len(response),
            succeeded=True,
        )

    def record_failed(self, *, source: AiCallSource, prompt: str) -> None:
        self._append(
            source=source,
            prompt=prompt,
            executed=True,
            succeeded=False,
        )

    def record_reused(self, *, source: AiCallSource, prompt: str) -> None:
        self._append(source=source, prompt=prompt, reused=True)

    def record_blocked(
        self, *, source: AiCallSource, prompt: str, reason: str
    ) -> None:
        self._append(source=source, prompt=prompt, blocked=True, block_reason=reason)

    def snapshot(
        self,
        *,
        knowledge_retrieval_count: int,
        agent_run_count: int,
        local_solution_avoided_ai: bool,
    ) -> ChallengeAiUsage:
        self._validate_count(knowledge_retrieval_count, "knowledge_retrieval_count")
        self._validate_count(agent_run_count, "agent_run_count")
        if not isinstance(local_solution_avoided_ai, bool):
            raise TypeError("local_solution_avoided_ai must be a boolean.")
        records = tuple(self._records)
        fingerprints = {record.prompt_fingerprint for record in records}
        return ChallengeAiUsage(
            records=records,
            attempted_calls=len(records),
            executed_calls=sum(record.executed for record in records),
            reused_calls=sum(record.reused for record in records),
            blocked_calls=sum(record.blocked for record in records),
            total_prompt_characters=sum(record.prompt_length for record in records),
            total_response_characters=sum(
                record.response_length or 0 for record in records
            ),
            unique_prompt_count=len(fingerprints),
            duplicate_prompt_count=len(records) - len(fingerprints),
            knowledge_retrieval_count=knowledge_retrieval_count,
            agent_run_count=agent_run_count,
            local_solution_avoided_ai=local_solution_avoided_ai,
        )

    def _append(
        self,
        *,
        source: AiCallSource,
        prompt: str,
        executed: bool = False,
        reused: bool = False,
        blocked: bool = False,
        block_reason: str | None = None,
        response_length: int | None = None,
        succeeded: bool | None = None,
    ) -> None:
        if len(self._records) >= self._max_records:
            raise RuntimeError("AI使用記録の上限に達しました。")
        if not isinstance(prompt, str):
            raise TypeError("prompt must be a string.")
        fingerprint = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        self._records.append(
            AiCallRecord(
                sequence=len(self._records),
                source=source,
                prompt_length=len(prompt),
                prompt_fingerprint=fingerprint,
                executed=executed,
                reused=reused,
                blocked=blocked,
                block_reason=block_reason,
                response_length=response_length,
                succeeded=succeeded,
            )
        )

    @staticmethod
    def _validate_count(value: int, name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an integer.")
        if value < 0:
            raise ValueError(f"{name} must be zero or greater.")
