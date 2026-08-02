import hashlib
from dataclasses import FrozenInstanceError, fields

import pytest

from app.client.base_client import BaseAIClient
from app.optimization import (
    AiBudgetExceededError,
    AiCallBlockedError,
    AiCallRecord,
    AiCallSource,
    AiUsageTracker,
    ChallengeAiSession,
    ChallengeAiUsage,
    SourceBoundAIClient,
)


class RecordingFakeAIClient(BaseAIClient):
    def __init__(self, responses: list[str | Exception] | None = None) -> None:
        self.prompts: list[str] = []
        self._responses = list(responses or ["固定回答"])

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        item = self._responses.pop(0) if self._responses else "固定回答"
        if isinstance(item, Exception):
            raise item
        return item


def _session(
    client: BaseAIClient | None = None,
    *,
    max_ai_calls: int = 4,
    cancel_requested=None,
) -> tuple[ChallengeAiSession, AiUsageTracker, BaseAIClient]:
    actual_client = client or RecordingFakeAIClient()
    tracker = AiUsageTracker()
    return (
        ChallengeAiSession(
            client=actual_client,
            tracker=tracker,
            max_ai_calls=max_ai_calls,
            cancel_requested=cancel_requested,
        ),
        tracker,
        actual_client,
    )


def _snapshot(tracker: AiUsageTracker) -> ChallengeAiUsage:
    return tracker.snapshot(
        knowledge_retrieval_count=1,
        agent_run_count=2,
        local_solution_avoided_ai=False,
    )


def test_ai_call_source_contains_only_real_ai_entry_points():
    assert set(AiCallSource) == {
        AiCallSource.CONTROLLER_FALLBACK,
        AiCallSource.CRYPTO_AGENT,
        AiCallSource.REV_AGENT,
        AiCallSource.WEB_AGENT,
        AiCallSource.FORENSICS_AGENT,
    }


def test_usage_dtos_are_frozen_slotted_and_do_not_store_content():
    tracker = AiUsageTracker()
    tracker.record_executed(
        source=AiCallSource.CRYPTO_AGENT,
        prompt="secret prompt",
        response="secret response",
    )
    usage = _snapshot(tracker)
    record = usage.records[0]
    assert not hasattr(record, "__dict__")
    assert not hasattr(usage, "__dict__")
    with pytest.raises(FrozenInstanceError):
        record.sequence = 4  # type: ignore[misc]
    record_fields = {item.name for item in fields(AiCallRecord)}
    assert "prompt" not in record_fields
    assert "response" not in record_fields
    assert "api_key" not in record_fields
    assert "secret prompt" not in repr(record)
    assert "secret response" not in repr(record)


def test_tracker_records_lengths_sequence_fingerprint_and_counts():
    tracker = AiUsageTracker()
    tracker.record_executed(
        source=AiCallSource.CONTROLLER_FALLBACK,
        prompt="abc",
        response="日本語",
    )
    tracker.record_reused(source=AiCallSource.CONTROLLER_FALLBACK, prompt="abc")
    tracker.record_blocked(
        source=AiCallSource.REV_AGENT,
        prompt="different",
        reason="上限",
    )
    usage = _snapshot(tracker)
    assert tuple(record.sequence for record in usage.records) == (0, 1, 2)
    assert usage.records[0].prompt_fingerprint == hashlib.sha256(b"abc").hexdigest()
    assert usage.attempted_calls == 3
    assert usage.executed_calls == 1
    assert usage.reused_calls == 1
    assert usage.blocked_calls == 1
    assert usage.total_prompt_characters == 3 + 3 + len("different")
    assert usage.total_response_characters == len("日本語")
    assert usage.unique_prompt_count == 2
    assert usage.duplicate_prompt_count == 1
    assert usage.knowledge_retrieval_count == 1
    assert usage.agent_run_count == 2


@pytest.mark.parametrize("value", [-1, True])
def test_tracker_snapshot_rejects_invalid_numeric_counts(value):
    with pytest.raises((TypeError, ValueError)):
        AiUsageTracker().snapshot(
            knowledge_retrieval_count=value,
            agent_run_count=0,
            local_solution_avoided_ai=False,
        )


def test_record_state_and_summary_consistency_are_validated():
    fingerprint = "0" * 64
    with pytest.raises(ValueError, match="Exactly one"):
        AiCallRecord(
            0,
            AiCallSource.CRYPTO_AGENT,
            0,
            fingerprint,
            True,
            True,
            False,
            None,
            0,
            True,
        )
    with pytest.raises(ValueError, match="attempted_calls"):
        ChallengeAiUsage((), 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, False)


def test_tracker_record_limit_is_bounded():
    tracker = AiUsageTracker(max_records=1)
    tracker.record_reused(source=AiCallSource.WEB_AGENT, prompt="one")
    with pytest.raises(RuntimeError, match="上限"):
        tracker.record_reused(source=AiCallSource.WEB_AGENT, prompt="two")


def test_same_source_and_exact_prompt_reuses_successful_response():
    client = RecordingFakeAIClient(["answer"])
    session, tracker, _ = _session(client)
    first = session.generate(source=AiCallSource.REV_AGENT, prompt="same")
    second = session.generate(source=AiCallSource.REV_AGENT, prompt="same")
    usage = _snapshot(tracker)
    assert first == second == "answer"
    assert client.prompts == ["same"]
    assert usage.executed_calls == 1
    assert usage.reused_calls == 1


def test_different_source_or_prompt_is_not_reused():
    client = RecordingFakeAIClient(["one", "two", "three"])
    session, tracker, _ = _session(client)
    assert session.generate(source=AiCallSource.CRYPTO_AGENT, prompt="same") == "one"
    assert session.generate(source=AiCallSource.REV_AGENT, prompt="same") == "two"
    assert session.generate(source=AiCallSource.REV_AGENT, prompt="other") == "three"
    usage = _snapshot(tracker)
    assert usage.executed_calls == 3
    assert usage.reused_calls == 0
    assert usage.unique_prompt_count == 2


def test_failed_response_is_recorded_but_never_cached():
    client = RecordingFakeAIClient([RuntimeError("temporary"), "recovered"])
    session, tracker, _ = _session(client)
    with pytest.raises(RuntimeError, match="temporary"):
        session.generate(source=AiCallSource.WEB_AGENT, prompt="retry-me")
    assert session.generate(source=AiCallSource.WEB_AGENT, prompt="retry-me") == "recovered"
    usage = _snapshot(tracker)
    assert client.prompts == ["retry-me", "retry-me"]
    assert usage.executed_calls == 2
    assert usage.records[0].succeeded is False
    assert usage.records[0].response_length is None


def test_budget_blocks_new_calls_but_allows_existing_cache_reuse():
    client = RecordingFakeAIClient(["cached"])
    session, tracker, _ = _session(client, max_ai_calls=1)
    assert session.generate(source=AiCallSource.CRYPTO_AGENT, prompt="one") == "cached"
    with pytest.raises(AiBudgetExceededError, match="上限"):
        session.generate(source=AiCallSource.CRYPTO_AGENT, prompt="two")
    assert session.generate(source=AiCallSource.CRYPTO_AGENT, prompt="one") == "cached"
    usage = _snapshot(tracker)
    assert client.prompts == ["one"]
    assert usage.executed_calls == 1
    assert usage.blocked_calls == 1
    assert usage.reused_calls == 1


def test_zero_budget_never_calls_client():
    session, tracker, client = _session(max_ai_calls=0)
    with pytest.raises(AiBudgetExceededError):
        session.generate(source=AiCallSource.CONTROLLER_FALLBACK, prompt="blocked")
    assert isinstance(client, RecordingFakeAIClient)
    assert client.prompts == []
    assert _snapshot(tracker).blocked_calls == 1


def test_cancellation_blocks_only_not_yet_started_calls():
    cancelled = False
    client = RecordingFakeAIClient(["before"])
    session, tracker, _ = _session(
        client, cancel_requested=lambda: cancelled
    )
    assert session.generate(source=AiCallSource.FORENSICS_AGENT, prompt="before") == "before"
    cancelled = True
    with pytest.raises(AiCallBlockedError, match="キャンセル"):
        session.generate(source=AiCallSource.FORENSICS_AGENT, prompt="after")
    assert client.prompts == ["before"]
    assert _snapshot(tracker).blocked_calls == 1


def test_source_bound_client_preserves_prompt_and_response():
    raw = RecordingFakeAIClient(["unchanged response"])
    session, tracker, _ = _session(raw)
    client = SourceBoundAIClient(
        session=session, source=AiCallSource.CONTROLLER_FALLBACK
    )
    assert client.generate("unchanged prompt") == "unchanged response"
    assert raw.prompts == ["unchanged prompt"]
    assert _snapshot(tracker).records[0].source is AiCallSource.CONTROLLER_FALLBACK


def test_separate_challenge_sessions_do_not_share_cache_or_usage():
    raw = RecordingFakeAIClient(["first", "second"])
    first, first_tracker, _ = _session(raw)
    second, second_tracker, _ = _session(raw)
    assert first.generate(source=AiCallSource.REV_AGENT, prompt="same") == "first"
    assert second.generate(source=AiCallSource.REV_AGENT, prompt="same") == "second"
    assert raw.prompts == ["same", "same"]
    assert _snapshot(first_tracker).executed_calls == 1
    assert _snapshot(second_tracker).executed_calls == 1


def test_local_solution_usage_snapshot_has_no_ai_attempts():
    usage = AiUsageTracker().snapshot(
        knowledge_retrieval_count=0,
        agent_run_count=1,
        local_solution_avoided_ai=True,
    )
    assert usage.attempted_calls == 0
    assert usage.executed_calls == 0
    assert usage.local_solution_avoided_ai is True
