from dataclasses import FrozenInstanceError

import pytest

from app.agents.agent import BaseAgent
from app.agents.agent_input import AgentInput
from app.agents.agent_result import AgentResult, AgentStatus, AgentType
from app.agents.agent_route_result import AgentRouteResult, AgentRouteStatus
from app.agents.agent_router import MAX_ERROR_MESSAGE_CHARACTERS, AgentRouter
from app.challenge.challenge_input import ChallengeInput


class FakeAgent(BaseAgent):
    def __init__(
        self,
        agent_type: AgentType,
        status: AgentStatus = AgentStatus.COMPLETED,
        error_message: str | None = None,
        error: BaseException | None = None,
    ) -> None:
        self._agent_type = agent_type
        self._status = status
        self._error_message = error_message
        self._error = error
        self.inputs: list[AgentInput] = []

    @property
    def agent_type(self) -> AgentType:
        return self._agent_type

    def analyze(self, agent_input: AgentInput) -> AgentResult:
        self.inputs.append(agent_input)
        if self._error is not None:
            raise self._error
        return AgentResult(
            agent_type=self.agent_type,
            status=self._status,
            summary="summary",
            answer="answer",
            flag_candidate=None,
            confidence=50,
            evidence=(),
            next_actions=(),
            error_message=self._error_message,
        )


def _input(category: str) -> AgentInput:
    return AgentInput(
        challenge=ChallengeInput("question"),
        category=category,
        context="context",
        local_knowledge=("knowledge",),
        metadata={"source": "test"},
    )


def test_router_accepts_agents_and_preserves_registration_order():
    web = FakeAgent(AgentType.WEB)
    crypto = FakeAgent(AgentType.CRYPTO)
    router = AgentRouter((web, crypto))

    assert router.agents == (web, crypto)


def test_duplicate_agent_type_is_rejected():
    with pytest.raises(ValueError, match="crypto.*重複"):
        AgentRouter((FakeAgent(AgentType.CRYPTO), FakeAgent(AgentType.CRYPTO)))


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("Crypto", AgentType.CRYPTO),
        ("Rev", AgentType.REV),
        ("Web", AgentType.WEB),
        ("Misc", AgentType.FORENSICS),
        ("Forensics", AgentType.FORENSICS),
        ("Unknown", AgentType.GENERAL),
        ("unrecognized", AgentType.GENERAL),
        ("  cRyPtO  ", AgentType.CRYPTO),
    ],
)
def test_category_is_mapped_explicitly_and_case_insensitively(category, expected):
    agent = FakeAgent(expected)

    route = AgentRouter((agent,)).route(_input(category))

    assert route.selected_agent is expected
    assert route.status is AgentRouteStatus.COMPLETED
    assert len(agent.inputs) == 1


@pytest.mark.parametrize(
    ("category", "selected"),
    [
        ("Crypto", AgentType.CRYPTO),
        ("Rev", AgentType.REV),
        ("Web", AgentType.WEB),
        ("Misc", AgentType.FORENSICS),
    ],
)
def test_only_selected_agent_runs(category, selected):
    agents = tuple(FakeAgent(agent_type) for agent_type in AgentType)

    route = AgentRouter(agents).route(_input(category))

    assert route.selected_agent is selected
    assert sum(len(agent.inputs) for agent in agents) == 1
    assert next(agent for agent in agents if agent.agent_type is selected).inputs
    assert all(
        not agent.inputs for agent in agents if agent.agent_type is not selected
    )


def test_original_agent_input_is_passed_without_mutation():
    agent = FakeAgent(AgentType.CRYPTO)
    agent_input = _input(" Crypto ")

    AgentRouter((agent,)).route(agent_input)

    assert agent.inputs == [agent_input]
    assert agent.inputs[0] is agent_input
    assert agent_input.category == " Crypto "
    assert dict(agent_input.metadata) == {"source": "test"}


@pytest.mark.parametrize(
    ("agent_status", "route_status"),
    [
        (AgentStatus.COMPLETED, AgentRouteStatus.COMPLETED),
        (AgentStatus.SKIPPED, AgentRouteStatus.SKIPPED),
        (AgentStatus.FAILED, AgentRouteStatus.FAILED),
    ],
)
def test_agent_status_is_converted_and_result_is_preserved(
    agent_status,
    route_status,
):
    agent = FakeAgent(AgentType.CRYPTO, agent_status, "agent failure")

    route = AgentRouter((agent,)).route(_input("Crypto"))

    assert route.status is route_status
    assert route.result is not None
    assert route.result.status is agent_status
    assert route.selected_agent is AgentType.CRYPTO
    assert route.error_message == "agent failure"


def test_agent_exception_becomes_failed_with_limited_details():
    message = "x" * (MAX_ERROR_MESSAGE_CHARACTERS + 100)
    agent = FakeAgent(AgentType.CRYPTO, error=RuntimeError(message))

    route = AgentRouter((agent,)).route(_input("Crypto"))

    assert route.status is AgentRouteStatus.FAILED
    assert route.result is None
    assert route.error_type == "RuntimeError"
    assert route.error_message == "x" * MAX_ERROR_MESSAGE_CHARACTERS


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit()])
def test_base_exceptions_are_not_caught(error):
    agent = FakeAgent(AgentType.CRYPTO, error=error)

    with pytest.raises(type(error)):
        AgentRouter((agent,)).route(_input("Crypto"))


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("Crypto", AgentType.CRYPTO),
        ("Unknown", AgentType.GENERAL),
        ("new category", AgentType.GENERAL),
    ],
)
def test_missing_expected_agent_returns_no_agent_without_fallback(category, expected):
    other = FakeAgent(AgentType.WEB)

    route = AgentRouter((other,)).route(_input(category))

    assert route == AgentRouteResult(
        category=category,
        selected_agent=expected,
        status=AgentRouteStatus.NO_AGENT,
        result=None,
        error_type=None,
        error_message=None,
    )
    assert other.inputs == []


def test_fake_general_agent_handles_unknown_category():
    general = FakeAgent(AgentType.GENERAL)

    route = AgentRouter((general,)).route(_input("Unknown"))

    assert route.status is AgentRouteStatus.COMPLETED
    assert route.selected_agent is AgentType.GENERAL
    assert len(general.inputs) == 1


def test_route_result_is_frozen_and_slotted():
    route = AgentRouter(()).route(_input("Unknown"))

    with pytest.raises(FrozenInstanceError):
        route.status = AgentRouteStatus.FAILED
    assert not hasattr(route, "__dict__")
