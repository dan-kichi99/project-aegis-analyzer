from app.analyzer.analyzer import Analyzer
from app.client.base_client import BaseAIClient
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


class FakeAIClient(BaseAIClient):
    """ドライランテスト用 Fake AI Client"""

    def __init__(self, response: str) -> None:
        self.response = response
        self.received_prompt: str | None = None

    def generate(self, prompt: str) -> str:
        self.received_prompt = prompt
        return self.response


def _create_production_like_controller(
    fake_ai_client: BaseAIClient,
) -> Controller:
    """本番に近い構成の Controller を構築するヘルパー関数"""

    analyzer = Analyzer()
    prompt_manager = PromptManager()
    knowledge_retriever = KnowledgeRetriever(
        base_dir="data/knowledge"
    )

    judge = Judge(
        flag_extractor=FlagExtractor(),
        confidence_estimator=ConfidenceEstimator(),
        reason_extractor=ReasonExtractor(),
        next_action_extractor=NextActionExtractor(),
        hypothesis_extractor=HypothesisExtractor(),
        gemini_prompt_generator=GeminiPromptGenerator(),
    )

    return Controller(
        analyzer=analyzer,
        knowledge_retriever=knowledge_retriever,
        prompt_manager=prompt_manager,
        ai_client=fake_ai_client,
        judge=judge,
    )


def test_dry_run_crypto_pipeline():
    fake_ai = FakeAIClient("Analysis complete. FLAG{fermat_factorization_success}")
    controller = _create_production_like_controller(fake_ai)

    question = "RSA Fermat factorization challenge"
    result = controller.process(question)

    # 1. Pipeline & Category
    assert result.category == "Crypto"
    assert result.flag == "FLAG{fermat_factorization_success}"

    # 2. Prompt verification
    assert fake_ai.received_prompt is not None
    assert "You are an expert in Cryptography and CTF challenges." in fake_ai.received_prompt
    assert "Relevant local knowledge:" in fake_ai.received_prompt
    assert "Fermat" in fake_ai.received_prompt or "rsa" in fake_ai.received_prompt.lower()

    # 3. Formatter verification
    formatter = ResultFormatter()
    formatted_output = formatter.format(result)
    assert isinstance(formatted_output, str)
    assert len(formatted_output) > 0
    assert "FLAG{fermat_factorization_success}" in formatted_output


def test_dry_run_web_pipeline():
    fake_ai = FakeAIClient("Vulnerability found: JWT None Algorithm. FLAG{jwt_none_bypass}")
    controller = _create_production_like_controller(fake_ai)

    question = "JWT algorithm none authentication bypass"
    result = controller.process(question)

    # 1. Pipeline & Category
    assert result.category == "Web"
    assert result.flag == "FLAG{jwt_none_bypass}"

    # 2. Prompt verification
    assert fake_ai.received_prompt is not None
    assert "You are an expert in Web Security and CTF challenges." in fake_ai.received_prompt
    assert "Relevant local knowledge:" in fake_ai.received_prompt
    assert "JWT" in fake_ai.received_prompt or "jwt" in fake_ai.received_prompt.lower()

    # 3. Formatter verification
    formatter = ResultFormatter()
    formatted_output = formatter.format(result)
    assert isinstance(formatted_output, str)
    assert len(formatted_output) > 0
    assert "FLAG{jwt_none_bypass}" in formatted_output


def test_dry_run_zero_match_pipeline():
    fake_ai = FakeAIClient("No vulnerability or flag found.")
    controller = _create_production_like_controller(fake_ai)

    question = "quantum spaceship banana"
    result = controller.process(question)

    # 1. Pipeline completed without crash
    assert fake_ai.received_prompt is not None

    # 2. Zero-match prompt verification
    assert "No local knowledge available." in fake_ai.received_prompt

    # 3. Formatter verification
    formatter = ResultFormatter()
    formatted_output = formatter.format(result)
    assert isinstance(formatted_output, str)
    assert len(formatted_output) > 0
