import hashlib
from collections.abc import Callable

from app.client.base_client import BaseAIClient
from app.optimization.ai_usage_result import AiCallSource
from app.optimization.ai_usage_tracker import AiUsageTracker

_BUDGET_MESSAGE = "このChallengeのAI呼び出し上限に達しました。"
_CANCEL_MESSAGE = "このChallengeの解析はキャンセルされました。"


class AiBudgetExceededError(RuntimeError):
    pass


class AiCallBlockedError(RuntimeError):
    pass


class ChallengeAiSession:
    def __init__(
        self,
        *,
        client: BaseAIClient,
        tracker: AiUsageTracker,
        max_ai_calls: int,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> None:
        if (
            isinstance(max_ai_calls, bool)
            or not isinstance(max_ai_calls, int)
            or max_ai_calls < 0
        ):
            raise ValueError("max_ai_calls must be a non-negative integer.")
        self._client = client
        self._tracker = tracker
        self._max_ai_calls = max_ai_calls
        self._cancel_requested = cancel_requested
        self._cache: dict[tuple[AiCallSource, str], str] = {}

    def generate(self, *, source: AiCallSource, prompt: str) -> str:
        fingerprint = self._fingerprint(prompt)
        key = (source, fingerprint)
        if key in self._cache:
            self._tracker.record_reused(source=source, prompt=prompt)
            return self._cache[key]
        if self._cancel_requested is not None and self._cancel_requested():
            self._tracker.record_blocked(
                source=source, prompt=prompt, reason=_CANCEL_MESSAGE
            )
            raise AiCallBlockedError(_CANCEL_MESSAGE)
        if self._tracker.executed_calls >= self._max_ai_calls:
            self._tracker.record_blocked(
                source=source, prompt=prompt, reason=_BUDGET_MESSAGE
            )
            raise AiBudgetExceededError(_BUDGET_MESSAGE)
        try:
            response = self._client.generate(prompt)
        except Exception:
            self._tracker.record_failed(source=source, prompt=prompt)
            raise
        if not isinstance(response, str):
            self._tracker.record_failed(source=source, prompt=prompt)
            raise TypeError("AI client response must be a string.")
        self._tracker.record_executed(
            source=source, prompt=prompt, response=response
        )
        self._cache[key] = response
        return response

    @staticmethod
    def _fingerprint(prompt: str) -> str:
        if not isinstance(prompt, str):
            raise TypeError("prompt must be a string.")
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


class SourceBoundAIClient(BaseAIClient):
    def __init__(
        self, *, session: ChallengeAiSession, source: AiCallSource
    ) -> None:
        if not isinstance(source, AiCallSource):
            raise TypeError("source must be AiCallSource.")
        self._session = session
        self._source = source

    def generate(self, prompt: str) -> str:
        return self._session.generate(source=self._source, prompt=prompt)
