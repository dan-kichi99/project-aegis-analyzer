import sys
from dataclasses import replace
from datetime import datetime, timezone

from app.analyzer.analyzer import Analyzer
from app.challenge.challenge_service import ChallengeService
from app.client.openai_client import OpenAIClient
from app.codegen.cli_code_approval import CliCodeApproval
from app.codegen.code_approval import CodeApprovalService
from app.config import Config
from app.controller.controller import Controller
from app.events.analysis_event import AnalysisEvent, AnalysisEventType
from app.events.cli_event_subscriber import CliEventSubscriber
from app.events.event_publisher import EventPublisher
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

    judge = Judge(
        flag_extractor=FlagExtractor(),
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
    )

    service = ChallengeService(
        controller=controller,
        analyzer=analyzer,
        event_publisher=publisher,
    )

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
