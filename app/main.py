import sys
from dataclasses import replace
from datetime import datetime, timezone

from app.agents.agent_coordinator import AgentCoordinator
from app.agents.agent_planner import AgentPlanner
from app.agents.agent_result_aggregator import AgentResultAggregator
from app.agents.agent_router import AgentRouter
from app.agents.crypto_agent import CryptoAgent
from app.agents.forensics_agent import ForensicsAgent
from app.agents.rev_agent import RevAgent
from app.agents.web_agent import WebAgent
from app.analyzer.analyzer import Analyzer
from app.challenge.challenge_context_builder import ChallengeContextBuilder
from app.challenge.challenge_service import ChallengeService
from app.client.openai_client import OpenAIClient
from app.codegen.cli_code_approval import CliCodeApproval
from app.codegen.code_approval import CodeApprovalService
from app.config import Config
from app.controller.controller import Controller
from app.events.analysis_event import AnalysisEvent, AnalysisEventType
from app.events.cli_event_subscriber import CliEventSubscriber
from app.events.event_publisher import EventPublisher
from app.execution.cli_python_execution import CliPythonExecution
from app.execution.execution_result_analyzer import ExecutionResultAnalyzer
from app.execution.python_execution_runner import PythonExecutionRunner
from app.judge.confidence_estimator import ConfidenceEstimator
from app.judge.flag_extractor import FlagExtractor
from app.judge.gemini_prompt_generator import GeminiPromptGenerator
from app.judge.hypothesis_extractor import HypothesisExtractor
from app.judge.judge import Judge
from app.judge.next_action_extractor import NextActionExtractor
from app.judge.reason_extractor import ReasonExtractor
from app.knowledge.knowledge_retriever import KnowledgeRetriever
from app.prompt.prompt_manager import PromptManager
from app.utils.result_formatter import ResultFormatter


def parse_file_paths(raw_input: str) -> list[str]:
    """カンマ区切りのファイルパスをリストへ変換する。"""
    if not raw_input or not raw_input.strip():
        return []

    return [
        path.strip()
        for path in raw_input.split(",")
        if path.strip()
    ]


def main() -> None:
    """Project Aegis Production CLI エントリーポイント。"""

    publisher = EventPublisher()
    publisher.subscribe(CliEventSubscriber())

    config = Config()

    ai_client = OpenAIClient(
        api_key=config.openai_api_key,
        model=config.openai_model,
    )

    analyzer = Analyzer()
    knowledge_retriever = KnowledgeRetriever()
    prompt_manager = PromptManager()
    context_builder = ChallengeContextBuilder()
    flag_extractor = FlagExtractor()

    agents = (
        CryptoAgent(ai_client, flag_extractor, prompt_manager),
        RevAgent(ai_client, flag_extractor, prompt_manager),
        WebAgent(ai_client, flag_extractor, prompt_manager),
        ForensicsAgent(ai_client, flag_extractor, prompt_manager),
    )
    agent_coordinator = AgentCoordinator(
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

    controller = Controller(
        analyzer=analyzer,
        knowledge_retriever=knowledge_retriever,
        prompt_manager=prompt_manager,
        ai_client=ai_client,
        judge=judge,
        event_publisher=publisher,
        context_builder=context_builder,
        agent_coordinator=agent_coordinator,
    )

    service = ChallengeService(
        controller=controller,
        analyzer=analyzer,
        event_publisher=publisher,
    )
    service.context_builder = context_builder

    formatter = ResultFormatter()

    try:
        print("問題文を入力してください：")
        question = input("> ")

        print(
            "添付ファイルのパスをカンマ区切りで入力してください。"
        )
        raw_files = input("> ")

        file_paths = parse_file_paths(raw_files)

        result = service.solve(
            question=question,
            file_paths=file_paths,
        )

        formatted_output = formatter.format(result)
        print(formatted_output)
        if result.generated_code is not None and result.generated_code.items:
            approval_cli = CliCodeApproval(CodeApprovalService())
            approved_code = approval_cli.review(result.generated_code)
            result = replace(result, generated_code=approved_code)
            execution_cli = CliPythonExecution(PythonExecutionRunner())
            execution_results = execution_cli.run_approved(approved_code)
            execution_analyzer = ExecutionResultAnalyzer(FlagExtractor())
            for execution_result in execution_results:
                print(formatter.format_execution(execution_result))
                execution_analysis = execution_analyzer.analyze(execution_result)
                print(formatter.format_execution_analysis(execution_analysis))

    except RuntimeError as error:
        _publish_failure(publisher, error)
        print(
            "AIとの通信中にエラーが発生しました。\n"
            f"詳細：{error}"
        )
        sys.exit(1)
    except (FileNotFoundError, ValueError) as error:
        _publish_failure(publisher, error)
        print(f"エラー：{error}")
        sys.exit(1)


def _publish_failure(
    publisher: EventPublisher,
    error: Exception,
) -> None:
    publisher.publish(
        AnalysisEvent(
            event_type=AnalysisEventType.ANALYSIS_FAILED,
            message="解析中にエラーが発生しました。",
            phase="completed",
            timestamp=datetime.now(timezone.utc),
            metadata={"error_type": type(error).__name__},
        )
    )


if __name__ == "__main__":
    main()
