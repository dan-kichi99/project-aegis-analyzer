import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.agents.agent_coordinator import AgentCoordinator
from app.agents.agent_planner import AgentPlanner
from app.agents.agent_result_aggregator import AgentResultAggregator
from app.agents.agent_router import AgentRouter
from app.agents.crypto_agent import CryptoAgent
from app.agents.forensics_agent import ForensicsAgent
from app.agents.rev_agent import RevAgent
from app.agents.web_agent import WebAgent
from app.analyzer.analyzer import Category
from app.application.analysis_worker import AnalysisWorker
from app.challenge.challenge_input import ChallengeInput
from app.challenge.challenge_service import ChallengeService
from app.client.base_client import BaseAIClient
from app.controller.controller import Controller
from app.judge.flag_extractor import FlagExtractor
from app.judge.judge_result import JudgeResult
from app.optimization import (
    AiBudgetExceededError,
    AiCallBlockedError,
    AiCallSource,
)
from app.prompt.prompt_manager import PromptManager


class ThreadSafeFakeAIClient(BaseAIClient):
    def __init__(self, response: str = "固定AI回答") -> None:
        self.response = response
        self.prompts: list[str] = []
        self._lock = threading.Lock()

    def generate(self, prompt: str) -> str:
        with self._lock:
            self.prompts.append(prompt)
        return self.response


def _judge() -> MagicMock:
    judge = MagicMock()
    judge.evaluate.side_effect = lambda category, answer: JudgeResult(
        category=category,
        answer=answer,
        flag=None,
        confidence=50,
        reason="固定理由",
        hypothesis=None,
        next_actions=[],
        gemini_prompt=None,
    )
    return judge


def _controller(
    category: str,
    *,
    client: ThreadSafeFakeAIClient | None = None,
    with_agents: bool = True,
    max_ai_calls: int = 3,
) -> tuple[Controller, ThreadSafeFakeAIClient, MagicMock, tuple[object, ...]]:
    raw = client or ThreadSafeFakeAIClient()
    analyzer = MagicMock()
    analyzer.analyze.return_value = category
    knowledge = MagicMock()
    knowledge.retrieve.return_value = ["固定Knowledge"]
    prompt_manager = PromptManager()
    agents: tuple[object, ...] = ()
    coordinator = None
    if with_agents:
        agent_raw = ThreadSafeFakeAIClient("共有Agentの元client")
        flag_extractor = FlagExtractor()
        agents = (
            CryptoAgent(agent_raw, flag_extractor, prompt_manager),
            RevAgent(agent_raw, flag_extractor, prompt_manager),
            WebAgent(agent_raw, flag_extractor, prompt_manager),
            ForensicsAgent(agent_raw, flag_extractor, prompt_manager),
        )
        coordinator = AgentCoordinator(
            planner=AgentPlanner(),
            router=AgentRouter(agents),
            aggregator=AgentResultAggregator(),
        )
    return (
        Controller(
            analyzer=analyzer,
            knowledge_retriever=knowledge,
            prompt_manager=prompt_manager,
            ai_client=raw,
            judge=_judge(),
            agent_coordinator=coordinator,
            max_ai_calls_per_challenge=max_ai_calls,
        ),
        raw,
        knowledge,
        agents,
    )


@pytest.mark.parametrize(
    ("category", "source"),
    [
        (Category.CRYPTO, AiCallSource.CRYPTO_AGENT),
        (Category.REV, AiCallSource.REV_AGENT),
        (Category.WEB, AiCallSource.WEB_AGENT),
        (Category.MISC, AiCallSource.FORENSICS_AGENT),
    ],
)
def test_real_agents_use_challenge_bound_source_without_controller_fallback(
    category: str,
    source: AiCallSource,
):
    controller, raw, knowledge, agents = _controller(category)
    execution = controller.process_challenge_with_usage(
        ChallengeInput(question="解析してください")
    )
    assert execution.ai_usage.executed_calls == 1
    assert execution.ai_usage.records[0].source is source
    assert execution.ai_usage.agent_run_count == 1
    assert len(raw.prompts) == 1
    assert knowledge.retrieve.call_count == 1
    assert execution.result.agent_result is not None
    for agent in agents:
        assert agent._ai_client.prompts == []  # type: ignore[attr-defined]


def test_controller_fallback_is_recorded_once_without_agents():
    controller, raw, knowledge, _ = _controller(Category.UNKNOWN, with_agents=False)
    execution = controller.process_challenge_with_usage(
        ChallengeInput(question="通常問題")
    )
    assert len(raw.prompts) == 1
    assert execution.ai_usage.executed_calls == 1
    assert execution.ai_usage.records[0].source is AiCallSource.CONTROLLER_FALLBACK
    assert execution.ai_usage.knowledge_retrieval_count == 1
    assert knowledge.retrieve.call_count == 1


def test_each_challenge_gets_independent_session_tracker_and_cache():
    controller, raw, _, _ = _controller(Category.UNKNOWN, with_agents=False)
    challenge = ChallengeInput(question="同じ問題")
    first = controller.process_challenge_with_usage(challenge)
    second = controller.process_challenge_with_usage(challenge)
    assert len(raw.prompts) == 2
    assert first.ai_usage is not second.ai_usage
    assert first.ai_usage.executed_calls == second.ai_usage.executed_calls == 1
    assert first.ai_usage.reused_calls == second.ai_usage.reused_calls == 0


def test_budget_zero_blocks_base_client_call():
    controller, raw, _, _ = _controller(
        Category.UNKNOWN, with_agents=False, max_ai_calls=0
    )
    with pytest.raises(AiBudgetExceededError):
        controller.process_challenge_with_usage(ChallengeInput(question="blocked"))
    assert raw.prompts == []


def test_cancel_callback_blocks_not_started_controller_call():
    controller, raw, _, _ = _controller(Category.UNKNOWN, with_agents=False)
    with pytest.raises(AiCallBlockedError):
        controller.process_challenge_with_usage(
            ChallengeInput(question="cancelled"),
            cancel_requested=lambda: True,
        )
    assert raw.prompts == []


def test_worker_cancel_is_forwarded_before_ai_call():
    controller, raw, _, _ = _controller(Category.UNKNOWN, with_agents=False)
    service = ChallengeService(controller=controller, analyzer=controller.analyzer)
    worker = AnalysisWorker(
        service.solve,
        "cancel before start",
        (),
        solve_with_cancel=service.solve_with_cancel,
    )
    worker.cancel()
    worker.start()
    worker.join(2)
    assert worker.completed is True
    assert isinstance(worker.error, AiCallBlockedError)
    assert raw.prompts == []


def test_local_challenge_service_solution_exposes_zero_ai_usage(tmp_path: Path):
    controller, raw, _, _ = _controller(Category.MISC)
    service = ChallengeService(controller=controller, analyzer=controller.analyzer)
    path = tmp_path / "flag.txt"
    path.write_text("FLAG{local_usage}", encoding="utf-8")
    execution = service.solve_with_usage("find flag", [path])
    assert execution.result.flag == "FLAG{local_usage}"
    assert execution.ai_usage.executed_calls == 0
    assert execution.ai_usage.local_solution_avoided_ai is True
    assert raw.prompts == []


def test_existing_public_return_types_remain_compatible():
    controller, _, _, _ = _controller(Category.UNKNOWN, with_agents=False)
    result = controller.process_challenge(ChallengeInput(question="compatibility"))
    assert isinstance(result, JudgeResult)
    service = ChallengeService(controller=controller, analyzer=controller.analyzer)
    assert isinstance(service.solve("compatibility", []), JudgeResult)


def test_parallel_challenges_do_not_mix_usage_or_cache():
    controller, raw, _, _ = _controller(Category.UNKNOWN, with_agents=False)
    results = []

    def run() -> None:
        results.append(
            controller.process_challenge_with_usage(
                ChallengeInput(question="parallel")
            )
        )

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 2
    assert len(raw.prompts) == 2
    assert all(item.ai_usage.executed_calls == 1 for item in results)
    assert results[0].ai_usage is not results[1].ai_usage


def test_usage_does_not_expose_prompt_response_or_api_key():
    controller, _, _, _ = _controller(Category.UNKNOWN, with_agents=False)
    usage = controller.process_challenge_with_usage(
        ChallengeInput(question="TOP_SECRET_PROMPT")
    ).ai_usage
    rendered = repr(usage)
    assert "TOP_SECRET_PROMPT" not in rendered
    assert "固定AI回答" not in rendered
    assert "api_key" not in rendered.casefold()
