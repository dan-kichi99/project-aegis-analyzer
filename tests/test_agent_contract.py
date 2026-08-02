import inspect
from dataclasses import FrozenInstanceError, fields

import pytest

from app.agents import (
    AgentEvidence,
    AgentInput,
    AgentResult,
    AgentStatus,
    AgentType,
    BaseAgent,
)
from app.challenge.challenge_input import ChallengeInput


def _input() -> AgentInput:
    return AgentInput(
        challenge=ChallengeInput(question="Analyze this challenge"),
        category="Crypto",
        context="問題文：Analyze this challenge",
        local_knowledge=("knowledge one", "knowledge two"),
        metadata={"request_id": "test-request"},
    )


def _result(
    *,
    status: AgentStatus = AgentStatus.COMPLETED,
    confidence: int | None = 80,
    error_message: str | None = None,
) -> AgentResult:
    return AgentResult(
        agent_type=AgentType.CRYPTO,
        status=status,
        summary="暗号問題を分析しました。",
        answer="回答候補",
        flag_candidate="FLAG{candidate}",
        confidence=confidence,
        evidence=(AgentEvidence("question", "RSA parameters", 70),),
        next_actions=("pとqを確認する", "復号結果を検証する"),
        error_message=error_message,
    )


class FakeAgent(BaseAgent):
    @property
    def agent_type(self) -> AgentType:
        return AgentType.CRYPTO

    def analyze(self, agent_input: AgentInput) -> AgentResult:
        return AgentResult(
            agent_type=self.agent_type,
            status=AgentStatus.COMPLETED,
            summary=f"{agent_input.category}を分析しました。",
            answer=agent_input.context,
            flag_candidate=None,
            confidence=60,
            evidence=(),
            next_actions=agent_input.local_knowledge,
            error_message=None,
        )


@pytest.mark.parametrize(
    "agent_type",
    [
        AgentType.CRYPTO,
        AgentType.REV,
        AgentType.WEB,
        AgentType.FORENSICS,
        AgentType.MISC,
        AgentType.GENERAL,
    ],
)
def test_agent_types_are_stable_string_enums(agent_type):
    assert AgentType(agent_type.value) is agent_type
    assert isinstance(agent_type.value, str)


@pytest.mark.parametrize(
    "status",
    [AgentStatus.COMPLETED, AgentStatus.SKIPPED, AgentStatus.FAILED],
)
def test_agent_statuses_are_stable_string_enums(status):
    assert AgentStatus(status.value) is status


def test_agent_input_holds_existing_challenge_context_knowledge_and_metadata():
    agent_input = _input()

    assert agent_input.challenge.question == "Analyze this challenge"
    assert agent_input.category == "Crypto"
    assert agent_input.context.startswith("問題文：")
    assert agent_input.local_knowledge == ("knowledge one", "knowledge two")
    assert agent_input.metadata == {"request_id": "test-request"}


def test_agent_input_copies_metadata_into_read_only_mapping():
    metadata = {"request_id": "original"}
    agent_input = AgentInput(
        ChallengeInput("question"), "Misc", "context", (), metadata
    )
    metadata["request_id"] = "changed"

    assert agent_input.metadata["request_id"] == "original"
    with pytest.raises(TypeError):
        agent_input.metadata["new"] = "value"


def test_agent_result_and_evidence_preserve_all_contract_fields():
    result = _result()

    assert result.agent_type is AgentType.CRYPTO
    assert result.status is AgentStatus.COMPLETED
    assert result.summary
    assert result.answer == "回答候補"
    assert result.flag_candidate == "FLAG{candidate}"
    assert result.confidence == 80
    assert result.evidence[0].source == "question"
    assert result.next_actions == ("pとqを確認する", "復号結果を検証する")
    assert result.error_message is None


@pytest.mark.parametrize("confidence", [0, 100, None])
def test_confidence_accepts_boundaries_and_none(confidence):
    assert _result(confidence=confidence).confidence == confidence
    assert AgentEvidence("source", "detail", confidence).confidence == confidence


@pytest.mark.parametrize("confidence", [-1, 101])
def test_agent_result_rejects_out_of_range_confidence(confidence):
    with pytest.raises(ValueError, match="confidence"):
        _result(confidence=confidence)


@pytest.mark.parametrize("confidence", [-1, 101])
def test_agent_evidence_rejects_out_of_range_confidence(confidence):
    with pytest.raises(ValueError, match="confidence"):
        AgentEvidence("source", "detail", confidence)


@pytest.mark.parametrize(
    ("status", "error_message"),
    [
        (AgentStatus.COMPLETED, None),
        (AgentStatus.SKIPPED, None),
        (AgentStatus.FAILED, "analysis failed"),
    ],
)
def test_result_represents_completed_skipped_and_failed(status, error_message):
    result = _result(status=status, error_message=error_message)

    assert result.status is status
    assert result.error_message == error_message


def test_flag_candidate_has_no_correctness_or_submission_state():
    names = {field.name for field in fields(AgentResult)}

    assert "flag_candidate" in names
    assert "correct" not in names
    assert "confirmed" not in names
    assert "submitted" not in names


def test_evidence_and_next_action_order_is_preserved():
    evidence = (
        AgentEvidence("first", "detail 1", 10),
        AgentEvidence("second", "detail 2", 20),
    )
    result = AgentResult(
        AgentType.REV,
        AgentStatus.COMPLETED,
        "summary",
        None,
        None,
        None,
        evidence,
        ("first action", "second action"),
        None,
    )

    assert result.evidence == evidence
    assert [item.source for item in result.evidence] == ["first", "second"]
    assert result.next_actions == ("first action", "second action")


@pytest.mark.parametrize(
    "dto",
    [
        _input(),
        AgentEvidence("source", "detail", None),
        _result(),
    ],
)
def test_dtos_are_slotted_and_frozen(dto):
    assert not hasattr(dto, "__dict__")
    field_name = fields(dto)[0].name
    with pytest.raises(FrozenInstanceError):
        setattr(dto, field_name, None)


def test_fake_agent_implements_common_interface_and_returns_agent_result():
    agent: BaseAgent = FakeAgent()

    result = agent.analyze(_input())

    assert agent.agent_type is AgentType.CRYPTO
    assert isinstance(result, AgentResult)
    assert result.agent_type is agent.agent_type
    assert result.status is AgentStatus.COMPLETED


def test_base_agent_cannot_be_instantiated_without_contract_implementation():
    with pytest.raises(TypeError):
        BaseAgent()


def test_base_agent_does_not_swallow_implementation_exceptions():
    class FailingAgent(FakeAgent):
        def analyze(self, agent_input: AgentInput) -> AgentResult:
            raise RuntimeError("unexpected agent failure")

    with pytest.raises(RuntimeError, match="unexpected agent failure"):
        FailingAgent().analyze(_input())


def test_agent_package_has_no_ui_event_process_or_global_registry_dependencies():
    modules = (
        __import__("app.agents.agent", fromlist=["*"]),
        __import__("app.agents.agent_input", fromlist=["*"]),
        __import__("app.agents.agent_result", fromlist=["*"]),
    )
    source = "\n".join(inspect.getsource(module) for module in modules).casefold()

    assert "app.main" not in source
    assert "cli" not in source
    assert "gui" not in source
    assert "eventpublisher" not in source
    assert "subprocess" not in source
    assert "singleton" not in source
    assert "registry" not in source
