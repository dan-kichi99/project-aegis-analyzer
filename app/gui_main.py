import os
import sys
from typing import Any

from dotenv import load_dotenv

from app.application.environment_diagnostics import EnvironmentDiagnostics
from app.application.startup_result import StartupMode, StartupStatus
from app.application.startup_service import StartupService
from app.client.base_client import BaseAIClient


class _UnavailableAIClient(BaseAIClient):
    def generate(self, _prompt: str) -> str:
        raise RuntimeError("OPENAI_API_KEYが設定されていません。")


def _ai_client() -> BaseAIClient:
    from app.client.openai_client import OpenAIClient

    api_key = os.getenv("OPENAI_API_KEY")

    if api_key is None or not api_key.strip():
        return _UnavailableAIClient()

    model = os.getenv("OPENAI_MODEL")

    return OpenAIClient(
        api_key=api_key.strip(),
        model=model.strip() if model and model.strip() else "gpt-4o-mini",
    )


def _build_application(
    root: object,
) -> tuple[Any, Any]:
    from app.agents.agent_coordinator import AgentCoordinator
    from app.agents.agent_planner import AgentPlanner
    from app.agents.agent_result_aggregator import AgentResultAggregator
    from app.agents.agent_router import AgentRouter
    from app.agents.crypto_agent import CryptoAgent
    from app.agents.forensics_agent import ForensicsAgent
    from app.agents.rev_agent import RevAgent
    from app.agents.web_agent import WebAgent
    from app.analyzer.analyzer import Analyzer
    from app.application.application_controller import ApplicationController
    from app.challenge.challenge_context_builder import ChallengeContextBuilder
    from app.challenge.challenge_service import ChallengeService
    from app.controller.controller import Controller
    from app.events.event_publisher import EventPublisher
    from app.gui.application_shell import ProjectAegisApplicationShell
    from app.judge.confidence_estimator import ConfidenceEstimator
    from app.judge.flag_extractor import FlagExtractor
    from app.judge.gemini_prompt_generator import GeminiPromptGenerator
    from app.judge.hypothesis_extractor import HypothesisExtractor
    from app.judge.judge import Judge
    from app.judge.next_action_extractor import NextActionExtractor
    from app.judge.reason_extractor import ReasonExtractor
    from app.knowledge.knowledge_retriever import KnowledgeRetriever
    from app.presentation import (
        ActionApprovalPresenter,
        AnalysisEventBuffer,
        AnalysisInputPresenter,
        ApplicationPresenter,
        CodeExecutionPresenter,
    )
    from app.prompt.prompt_manager import PromptManager

    publisher = EventPublisher()
    ai_client = _ai_client()
    analyzer = Analyzer()
    prompt_manager = PromptManager()
    flag_extractor = FlagExtractor()

    agents = (
        CryptoAgent(ai_client, flag_extractor, prompt_manager),
        RevAgent(ai_client, flag_extractor, prompt_manager),
        WebAgent(ai_client, flag_extractor, prompt_manager),
        ForensicsAgent(ai_client, flag_extractor, prompt_manager),
    )

    coordinator = AgentCoordinator(
        planner=AgentPlanner(),
        router=AgentRouter(agents),
        aggregator=AgentResultAggregator(),
        event_publisher=publisher,
    )

    judge = Judge(
        flag_extractor=flag_extractor,
        confidence_estimator=ConfidenceEstimator(),
        reason_extractor=ReasonExtractor(),
        next_action_extractor=NextActionExtractor(),
        hypothesis_extractor=HypothesisExtractor(),
        gemini_prompt_generator=GeminiPromptGenerator(),
    )

    application_controller = ApplicationController(
        ChallengeService(
            controller=Controller(
                analyzer=analyzer,
                knowledge_retriever=KnowledgeRetriever(),
                prompt_manager=prompt_manager,
                ai_client=ai_client,
                judge=judge,
                context_builder=ChallengeContextBuilder(),
                event_publisher=publisher,
                agent_coordinator=coordinator,
            ),
            analyzer=analyzer,
            event_publisher=publisher,
        ),
        publisher,
    )

    event_buffer = AnalysisEventBuffer()

    shell = ProjectAegisApplicationShell(
        root,
        input_presenter=AnalysisInputPresenter(),
        application_presenter=ApplicationPresenter(),
        action_approval_presenter=ActionApprovalPresenter(),
        code_execution_presenter=CodeExecutionPresenter(),
        event_buffer=event_buffer,
        on_analysis_requested=application_controller.handle_analysis_request,
        on_action_decision=application_controller.handle_action_decision,
        on_code_decision=application_controller.handle_code_decision,
        on_code_execution_requested=(
            application_controller.handle_code_execution_request
        ),
        on_cancel_requested=application_controller.cancel_analysis,
        result_provider=lambda: application_controller.last_result,
    )

    application_controller.connect_shell(shell)

    return shell, application_controller


def _create_root() -> Any:
    import tkinter as tk

    return tk.Tk()


def main() -> int:
    load_dotenv()

    startup = StartupService(
        diagnostics=EnvironmentDiagnostics()
    ).check(StartupMode.GUI)

    if startup.status in {
        StartupStatus.BLOCKED,
        StartupStatus.FAILED,
    }:
        print(startup.message, file=sys.stderr)
        return startup.exit_code

    if startup.status is StartupStatus.DEGRADED:
        print(startup.message, file=sys.stderr)

    root: Any | None = None
    shell: Any | None = None
    controller: Any | None = None

    try:
        root = _create_root()
        root.title("Project Aegis")

        shell, controller = _build_application(root)

        shell.frame.pack(fill="both", expand=True)
        shell.start_event_bridge()

        root.mainloop()

        return 0

    except Exception:  # noqa: BLE001 - GUI entrypoint hides environment details
        print(
            "GUIの起動中にエラーが発生しました。",
            file=sys.stderr,
        )
        return 1

    finally:
        if shell is not None:
            shell.stop_event_bridge()

        if controller is not None:
            controller.disconnect_shell()

        if root is not None:
            root.destroy()


if __name__ == "__main__":
    raise SystemExit(main())