import inspect
from unittest.mock import MagicMock, patch

import pytest

from app.agents.agent import BaseAgent
from app.agents.agent_aggregate_result import AgentAggregateResult, AgentConflict
from app.agents.agent_coordinator import AgentCoordinator
from app.agents.agent_input import AgentInput
from app.agents.agent_plan import AgentCandidate, AgentExecutionPlan
from app.agents.agent_planner import AgentPlanner
from app.agents.agent_result import AgentEvidence, AgentResult, AgentStatus, AgentType
from app.agents.agent_result_aggregator import AgentResultAggregator
from app.agents.agent_router import AgentRouter
from app.agents.crypto_agent import CryptoAgent
from app.agents.rev_agent import RevAgent
from app.analyzer.analyzer import Analyzer
from app.challenge.challenge_input import ChallengeInput
from app.challenge.challenge_service import ChallengeService
from app.client.base_client import BaseAIClient
from app.controller.controller import Controller
from app.events.analysis_event import AnalysisEventType
from app.events.event_publisher import EventPublisher
from app.file.file_analysis_result import FileAnalysisResult
from app.judge.judge_result import JudgeResult
from app.main import main
from app.prompt.prompt_manager import PromptManager
from app.utils.result_formatter import ResultFormatter


class RecordingAIClient(BaseAIClient):
    def __init__(self, response="controller answer"):
        self.response = response
        self.prompts = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class FakeAgent(BaseAgent):
    def __init__(self, agent_type, result=None, error=None, order=None):
        self._type = agent_type
        self.result = result or _result(agent_type)
        self.error = error
        self.inputs = []
        self.order = order

    @property
    def agent_type(self):
        return self._type

    def analyze(self, agent_input):
        self.inputs.append(agent_input)
        if self.order is not None:
            self.order.append(self.agent_type)
        if self.error is not None:
            raise self.error
        return self.result


class FixedPlanner:
    def __init__(self, plan):
        self.result = plan
        self.inputs = []

    def plan(self, agent_input):
        self.inputs.append(agent_input)
        return self.result


def _result(
    agent_type,
    status=AgentStatus.COMPLETED,
    flag=None,
    answer="agent answer",
    confidence=60,
):
    return AgentResult(
        agent_type,
        status,
        "summary",
        answer,
        flag,
        confidence,
        (AgentEvidence("source", "detail", 50),),
        ("next",),
        "failure" if status is AgentStatus.FAILED else None,
    )


def _plan(*types, category="Unknown"):
    return AgentExecutionPlan(
        category,
        tuple(
            AgentCandidate(agent_type, 100 - index * 10, "reason", index == 0)
            for index, agent_type in enumerate(types)
        ),
    )


def _input(category="Unknown", files=None):
    return AgentInput(
        ChallengeInput("question", files or []),
        category,
        "context",
        ("knowledge",),
        {"file_count": len(files or [])},
    )


def _coordinator(plan, agents, publisher=None, max_agents=2):
    planner = FixedPlanner(plan)
    coordinator = AgentCoordinator(
        planner,
        AgentRouter(tuple(agents)),
        AgentResultAggregator(),
        max_agents,
        publisher,
    )
    return coordinator, planner


def _controller(coordinator, ai_client=None, knowledge=None):
    ai_client = ai_client or RecordingAIClient()
    knowledge = knowledge or MagicMock()
    knowledge.retrieve.return_value = ["knowledge"]
    judge = MagicMock()
    judge.evaluate.side_effect = lambda category, answer: JudgeResult(
        category=category,
        answer=answer,
        confidence=40,
    )
    return (
        Controller(
            Analyzer(),
            knowledge,
            PromptManager(),
            ai_client,
            judge,
            agent_coordinator=coordinator,
        ),
        ai_client,
        knowledge,
        judge,
    )


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("RSA cipher", AgentType.CRYPTO),
        ("Reverse ELF", AgentType.REV),
        ("HTTP request", AgentType.WEB),
        ("Analyze PNG", AgentType.FORENSICS),
    ],
)
def test_analyzer_category_selects_expected_primary_agent(question, expected):
    agent = FakeAgent(expected)
    coordinator = AgentCoordinator(
        AgentPlanner(),
        AgentRouter((agent,)),
        AgentResultAggregator(),
    )
    controller, ai_client, _, _ = _controller(coordinator)

    result = controller.process_challenge(ChallengeInput(question))

    assert result.agent_result is not None
    assert result.agent_result.primary_result.agent_type is expected
    assert len(agent.inputs) == 1
    assert ai_client.prompts == []


def test_agent_input_contains_prepared_data_and_knowledge_is_retrieved_once():
    agent = FakeAgent(AgentType.CRYPTO)
    coordinator, planner = _coordinator(_plan(AgentType.CRYPTO), [agent])
    controller, _, knowledge, _ = _controller(coordinator)
    challenge = ChallengeInput("RSA challenge")

    controller.process_challenge(challenge)

    knowledge.retrieve.assert_called_once_with("Crypto", "RSA challenge")
    agent_input = planner.inputs[0]
    assert agent_input.challenge is challenge
    assert agent_input.category == "Crypto"
    assert "問題文：" in agent_input.context
    assert agent_input.local_knowledge == ("knowledge",)
    assert dict(agent_input.metadata) == {"file_count": 0}
    assert "key" not in repr(agent_input.metadata).casefold()


def test_only_first_two_agents_run_sequentially_in_plan_order():
    order = []
    agents = [
        FakeAgent(AgentType.CRYPTO, order=order),
        FakeAgent(AgentType.REV, order=order),
        FakeAgent(AgentType.FORENSICS, order=order),
    ]
    coordinator, _ = _coordinator(
        _plan(AgentType.CRYPTO, AgentType.REV, AgentType.FORENSICS),
        agents,
    )

    aggregate = coordinator.analyze(_input("Crypto"))

    assert order == [AgentType.CRYPTO, AgentType.REV]
    assert [item.agent_type for item in aggregate.results] == order
    assert agents[2].inputs == []


def test_primary_flag_stops_auxiliary_and_is_not_confirmed_by_controller():
    primary = FakeAgent(
        AgentType.CRYPTO,
        _result(AgentType.CRYPTO, flag="FLAG{candidate}", confidence=90),
    )
    auxiliary = FakeAgent(AgentType.REV)
    coordinator, _ = _coordinator(
        _plan(AgentType.CRYPTO, AgentType.REV),
        [primary, auxiliary],
    )
    controller, ai_client, _, _ = _controller(coordinator)

    result = controller.process_challenge(ChallengeInput("RSA challenge"))

    assert len(primary.inputs) == 1
    assert auxiliary.inputs == []
    assert ai_client.prompts == []
    assert result.flag is None
    assert result.agent_result.primary_flag == "FLAG{candidate}"
    assert "未確定" in result.reason


def test_no_primary_flag_runs_at_most_one_auxiliary():
    primary = FakeAgent(AgentType.CRYPTO)
    auxiliary = FakeAgent(AgentType.REV)
    coordinator, _ = _coordinator(
        _plan(AgentType.CRYPTO, AgentType.REV),
        [primary, auxiliary],
    )

    aggregate = coordinator.analyze(_input("Crypto"))

    assert len(primary.inputs) == len(auxiliary.inputs) == 1
    assert len(aggregate.results) == 2


def test_failed_primary_runs_auxiliary_without_retry():
    primary = FakeAgent(AgentType.CRYPTO, error=RuntimeError("failed"))
    auxiliary = FakeAgent(AgentType.REV)
    coordinator, _ = _coordinator(
        _plan(AgentType.CRYPTO, AgentType.REV),
        [primary, auxiliary],
    )

    aggregate = coordinator.analyze(_input("Crypto"))

    assert len(primary.inputs) == len(auxiliary.inputs) == 1
    assert aggregate.results[0].status is AgentStatus.FAILED
    assert aggregate.primary_result.agent_type is AgentType.REV
    assert aggregate.used_fallback


def test_unregistered_general_uses_highest_registered_structured_auxiliary():
    rev = FakeAgent(AgentType.REV)
    coordinator = AgentCoordinator(
        AgentPlanner(),
        AgentRouter((rev,)),
        AgentResultAggregator(),
    )
    elf = FileAnalysisResult(
        "sample.elf", 10, ".elf", "elf", None, [], elf_info=object()
    )

    aggregate = coordinator.analyze(_input(files=[elf]))

    assert len(rev.inputs) == 1
    assert rev.inputs[0].category == "Unknown"
    assert rev.inputs[0].target_agent is AgentType.REV
    assert aggregate.primary_result.agent_type is AgentType.REV
    assert aggregate.used_fallback


@pytest.mark.parametrize(
    ("agent_type", "agent_class"),
    [
        (AgentType.REV, RevAgent),
        (AgentType.CRYPTO, CryptoAgent),
    ],
)
def test_unknown_category_runs_explicit_target_without_rewriting_category(
    agent_type,
    agent_class,
):
    ai_client = RecordingAIClient("specialized analysis")
    agent_input = _input("Unknown")
    targeted = AgentInput(
        challenge=agent_input.challenge,
        category=agent_input.category,
        context=agent_input.context,
        local_knowledge=agent_input.local_knowledge,
        metadata=agent_input.metadata,
        target_agent=agent_type,
    )

    result = agent_class(ai_client).analyze(targeted)

    assert result.status is AgentStatus.COMPLETED
    assert targeted.category == "Unknown"
    assert targeted.target_agent is agent_type
    assert len(ai_client.prompts) == 1


def test_target_agent_mismatch_skips_and_none_keeps_legacy_category_behavior():
    ai_client = RecordingAIClient()
    mismatched = AgentInput(
        ChallengeInput("question"),
        "Rev",
        "context",
        (),
        target_agent=AgentType.CRYPTO,
    )

    assert RevAgent(ai_client).analyze(mismatched).status is AgentStatus.SKIPPED
    assert ai_client.prompts == []
    legacy = AgentInput(ChallengeInput("question"), "Rev", "context", ())
    assert RevAgent(ai_client).analyze(legacy).status is AgentStatus.COMPLETED
    assert len(ai_client.prompts) == 1


def test_misc_category_is_preserved_when_rev_is_explicit_target():
    original = _input("Misc")
    rev = FakeAgent(AgentType.REV)
    coordinator, planner = _coordinator(
        _plan(AgentType.REV, category="Misc"),
        [rev],
    )

    aggregate = coordinator.analyze(original)

    assert original.category == "Misc"
    assert original.target_agent is None
    assert planner.inputs[0] is original
    assert planner.result.category == "Misc"
    assert rev.inputs[0].category == "Misc"
    assert rev.inputs[0].target_agent is AgentType.REV
    assert aggregate.category == "Misc"
    assert aggregate.results[0].agent_type is AgentType.REV


def test_no_registered_agent_falls_back_to_controller_once():
    coordinator, _ = _coordinator(_plan(AgentType.GENERAL), [])
    controller, ai_client, knowledge, judge = _controller(coordinator)

    result = controller.process_challenge(ChallengeInput("ordinary"))

    assert result.agent_result is None
    assert len(ai_client.prompts) == 1
    knowledge.retrieve.assert_called_once()
    judge.evaluate.assert_called_once()


@pytest.mark.parametrize("status", [AgentStatus.SKIPPED, AgentStatus.FAILED])
def test_unusable_agent_result_falls_back_without_double_ai(status):
    answer = None
    agent = FakeAgent(AgentType.GENERAL, _result(AgentType.GENERAL, status, answer=answer))
    coordinator, _ = _coordinator(_plan(AgentType.GENERAL), [agent])
    controller, ai_client, _, _ = _controller(coordinator)

    result = controller.process_challenge(ChallengeInput("ordinary"))

    assert result.agent_result is None
    assert len(ai_client.prompts) == 1
    assert len(agent.inputs) == 1


def test_completed_agent_prevents_controller_ai_and_preserves_aggregate_fields():
    agent_result = AgentResult(
        AgentType.CRYPTO,
        AgentStatus.COMPLETED,
        "summary",
        "specialized answer",
        None,
        75,
        (AgentEvidence("rsa", "n=15", 75),),
        ("verify",),
        None,
    )
    agent = FakeAgent(AgentType.CRYPTO, agent_result)
    coordinator, _ = _coordinator(_plan(AgentType.CRYPTO), [agent])
    controller, ai_client, _, judge = _controller(coordinator)

    result = controller.process_challenge(ChallengeInput("RSA challenge"))

    assert result.answer == "specialized answer"
    assert result.confidence == 75
    assert result.next_actions == ["verify"]
    assert result.agent_result.evidence
    assert result.flag is None
    assert ai_client.prompts == []
    judge.evaluate.assert_not_called()


def test_events_are_ordered_and_metadata_has_no_payload_or_flag():
    publisher = EventPublisher()
    events = []
    publisher.subscribe(events.append)
    primary = FakeAgent(AgentType.CRYPTO)
    auxiliary = FakeAgent(AgentType.REV, _result(AgentType.REV, flag="FLAG{secret}"))
    coordinator, _ = _coordinator(
        _plan(AgentType.CRYPTO, AgentType.REV),
        [primary, auxiliary],
        publisher,
    )

    coordinator.analyze(_input("Crypto"))

    assert [event.event_type for event in events] == [
        AnalysisEventType.AGENT_PLAN_CREATED,
        AnalysisEventType.AGENT_STARTED,
        AnalysisEventType.AGENT_COMPLETED,
        AnalysisEventType.AGENT_STARTED,
        AnalysisEventType.AGENT_COMPLETED,
        AnalysisEventType.AGENT_AGGREGATION_COMPLETED,
    ]
    metadata = repr([dict(event.metadata) for event in events])
    assert "FLAG{secret}" not in metadata
    assert "prompt" not in metadata.casefold()
    assert "api_key" not in metadata.casefold()


def test_agent_failure_event_and_subscriber_failure_do_not_stop_pipeline():
    publisher = EventPublisher()
    events = []
    publisher.subscribe(lambda event: (_ for _ in ()).throw(RuntimeError("subscriber")))
    publisher.subscribe(events.append)
    agent = FakeAgent(AgentType.CRYPTO, error=RuntimeError("agent failed"))
    coordinator, _ = _coordinator(_plan(AgentType.CRYPTO), [agent], publisher)

    aggregate = coordinator.analyze(_input("Crypto"))

    assert aggregate.status is AgentStatus.FAILED
    assert AnalysisEventType.AGENT_FAILED in [event.event_type for event in events]


def test_formatter_displays_agent_candidates_conflicts_and_warning():
    first = _result(AgentType.CRYPTO, flag="FLAG{a}", confidence=80)
    second = _result(AgentType.REV, flag="FLAG{b}", confidence=70)
    aggregate = AgentAggregateResult(
        results=(first, second),
        primary_result=first,
        status=AgentStatus.COMPLETED,
        summary="2件を統合しました。",
        flag_candidates=("FLAG{a}", "FLAG{b}"),
        primary_flag="FLAG{a}",
        confidence=80,
        evidence=(AgentEvidence("[crypto] source", "detail", 50),),
        next_actions=("verify",),
        conflicts=(
            AgentConflict(
                "flag_candidate",
                ("FLAG{a}", "FLAG{b}"),
                (AgentType.CRYPTO, AgentType.REV),
            ),
        ),
    )
    output = ResultFormatter().format(
        JudgeResult("Crypto", "answer", agent_result=aggregate)
    )

    for expected in (
        "専門Agent解析",
        "主担当：Crypto",
        "実行Agent：Crypto、Rev",
        "FLAG{a}",
        "正解であることは保証されません。",
        "Evidence：",
        "競合情報：",
    ):
        assert expected in output


def test_formatter_without_agent_result_keeps_existing_display():
    output = ResultFormatter().format(JudgeResult("Misc", "answer"))

    assert "専門Agent解析" not in output
    assert "Project Aegis 解析結果" in output


def test_coordinator_rejects_more_than_two_agents():
    with pytest.raises(ValueError, match="1件または2件"):
        AgentCoordinator(
            AgentPlanner(),
            AgentRouter(()),
            AgentResultAggregator(),
            max_agents=3,
        )


def test_main_composes_four_agents_with_shared_ai_and_publisher():
    publisher = EventPublisher()
    ai_client = RecordingAIClient()
    with (
        patch("app.main.EventPublisher", return_value=publisher),
        patch("app.main.Config") as config_cls,
        patch("app.main.OpenAIClient", return_value=ai_client),
        patch("app.main.Controller") as controller_cls,
        patch("app.main.ChallengeService") as service_cls,
        patch("builtins.input", side_effect=["question", ""]),
        patch("builtins.print"),
    ):
        config_cls.return_value.openai_api_key = "test-key"
        config_cls.return_value.openai_model = "test-model"
        service_cls.return_value.solve.return_value = JudgeResult("Misc", "done")

        main()

    coordinator = controller_cls.call_args.kwargs["agent_coordinator"]
    agents = coordinator.router.agents
    assert [agent.agent_type for agent in agents] == [
        AgentType.CRYPTO,
        AgentType.REV,
        AgentType.WEB,
        AgentType.FORENSICS,
    ]
    assert all(agent._ai_client is ai_client for agent in agents)
    assert isinstance(coordinator.planner, AgentPlanner)
    assert isinstance(coordinator.aggregator, AgentResultAggregator)
    assert coordinator._event_publisher is publisher
    assert controller_cls.call_args.kwargs["event_publisher"] is publisher


def test_specialized_service_event_order_has_single_analysis_completed():
    publisher = EventPublisher()
    events = []
    publisher.subscribe(events.append)
    agent = FakeAgent(AgentType.CRYPTO)
    coordinator, _ = _coordinator(_plan(AgentType.CRYPTO), [agent], publisher)
    controller, _, _, _ = _controller(coordinator)
    service = ChallengeService(controller, Analyzer(), event_publisher=publisher)

    service.solve("RSA challenge")

    types = [event.event_type for event in events]
    assert types == [
        AnalysisEventType.ANALYSIS_STARTED,
        AnalysisEventType.AGENT_PLAN_CREATED,
        AnalysisEventType.AGENT_STARTED,
        AnalysisEventType.AGENT_COMPLETED,
        AnalysisEventType.AGENT_AGGREGATION_COMPLETED,
        AnalysisEventType.ANALYSIS_COMPLETED,
    ]
    assert types.count(AnalysisEventType.ANALYSIS_COMPLETED) == 1
    assert AnalysisEventType.AI_ANALYSIS_STARTED not in types


def test_coordinator_has_no_parallel_process_execution_or_retry_dependency():
    source = inspect.getsource(
        __import__("app.agents.agent_coordinator", fromlist=["*"])
    ).casefold()
    for forbidden in ("subprocess", "asyncio", "thread", "executor", "retry", "exec("):
        assert forbidden not in source
