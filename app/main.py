import sys

from app.analyzer.analyzer import Analyzer
from app.challenge.challenge_service import ChallengeService
from app.client.openai_client import OpenAIClient
from app.config import Config
from app.controller.controller import Controller
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
    )

    service = ChallengeService(
        controller=controller,
        analyzer=analyzer,
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

        print(
            "========================\n"
            "Project Aegis\n"
            "解析中...\n"
            "========================",
            flush=True,
        )

        result = service.solve(
            question=question,
            file_paths=file_paths,
        )

        formatted_output = formatter.format(result)
        print(formatted_output)

    except RuntimeError as error:
        print(
            "AIとの通信中にエラーが発生しました。\n"
            f"詳細：{error}"
        )
        sys.exit(1)
    except (FileNotFoundError, ValueError) as error:
        print(f"エラー：{error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
