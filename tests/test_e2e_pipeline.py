from pathlib import Path

import pytest

from app.ai.base import BaseAIClient
from app.analyzer.analyzer import Analyzer, Category
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
    """テスト用Fake AI Client。直近のプロンプトを保持する。"""

    def __init__(self, response_text: str) -> None:
        self._response_text = response_text
        self.last_prompt: str | None = None

    def generate(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self._response_text


def _create_judge() -> Judge:
    """現在のJudge依存をすべて組み立てる。"""
    return Judge(
        flag_extractor=FlagExtractor(),
        confidence_estimator=ConfidenceEstimator(),
        reason_extractor=ReasonExtractor(),
        next_action_extractor=NextActionExtractor(),
        hypothesis_extractor=HypothesisExtractor(),
        gemini_prompt_generator=GeminiPromptGenerator(),
    )


def _create_controller(
    fake_ai_client: FakeAIClient,
    knowledge_retriever: KnowledgeRetriever,
    analyzer: Analyzer | None = None,
    prompt_manager: PromptManager | None = None,
    judge: Judge | None = None,
) -> Controller:
    """現行Controller仕様に合わせて依存を明示的に注入する。"""
    return Controller(
        analyzer=analyzer or Analyzer(),
        knowledge_retriever=knowledge_retriever,
        prompt_manager=prompt_manager or PromptManager(),
        ai_client=fake_ai_client,
        judge=judge or _create_judge(),
    )


@pytest.fixture
def temp_knowledge_dir(tmp_path: Path) -> Path:
    crypto_dir = tmp_path / "crypto"
    crypto_dir.mkdir(parents=True)

    (crypto_dir / "rsa.txt").write_text(
        "RSA private key factorization information.",
        encoding="utf-8",
    )

    return tmp_path


@pytest.fixture
def setup_components():
    analyzer = Analyzer()
    prompt_manager = PromptManager()
    judge = _create_judge()
    result_formatter = ResultFormatter()

    return {
        "analyzer": analyzer,
        "prompt_manager": prompt_manager,
        "judge": judge,
        "result_formatter": result_formatter,
    }


def test_e2e_pipeline_crypto(
    setup_components,
    temp_knowledge_dir: Path,
):
    crypto_response = (
        "Here is the solution for RSA problem. flag{test_flag}"
    )

    fake_ai_client = FakeAIClient(crypto_response)

    knowledge_retriever = KnowledgeRetriever(
        base_dir=temp_knowledge_dir
    )

    controller = _create_controller(
        fake_ai_client=fake_ai_client,
        knowledge_retriever=knowledge_retriever,
        analyzer=setup_components["analyzer"],
        prompt_manager=setup_components["prompt_manager"],
        judge=setup_components["judge"],
    )

    question = "Decrypt this RSA ciphertext"
    result = controller.process(question)

    formatted_output = (
        setup_components["result_formatter"].format(result)
    )

    assert result.gemini_prompt is None
    assert (
        "You are an expert in Cryptography and CTF challenges."
        in fake_ai_client.last_prompt
    )
    assert (
        "RSA private key factorization information."
        in fake_ai_client.last_prompt
    )

    assert result.category == Category.CRYPTO
    assert result.flag == "flag{test_flag}"
    assert result.confidence is not None
    assert result.confidence >= 90
    assert result.hypothesis is None
    assert result.next_actions == []
    assert result.gemini_prompt is None

    assert (
        "カテゴリ\n================\n暗号"
        in formatted_output
    )

    assert (
        "Flag候補\n================\nflag{test_flag}"
        in formatted_output
    )


def test_e2e_pipeline_web(
    setup_components,
    temp_knowledge_dir: Path,
):
    web_response = (
        "This looks like an SQL Injection vulnerability."
    )

    fake_ai_client = FakeAIClient(web_response)

    knowledge_retriever = KnowledgeRetriever(
        base_dir=temp_knowledge_dir
    )

    controller = _create_controller(
        fake_ai_client=fake_ai_client,
        knowledge_retriever=knowledge_retriever,
        analyzer=setup_components["analyzer"],
        prompt_manager=setup_components["prompt_manager"],
        judge=setup_components["judge"],
    )

    question = "How to bypass SQL login form?"
    result = controller.process(question)

    assert fake_ai_client.last_prompt is not None

    assert (
        "You are an expert in Web Security and CTF challenges."
        in fake_ai_client.last_prompt
    )

    assert (
        "No local knowledge available."
        in fake_ai_client.last_prompt
    )

    assert result.category == Category.WEB
    assert result.flag is None


def test_e2e_pipeline_rev(
    setup_components,
    temp_knowledge_dir: Path,
):
    fake_ai_client = FakeAIClient(
        "Analyze the binary using Ghidra."
    )

    knowledge_retriever = KnowledgeRetriever(
        base_dir=temp_knowledge_dir
    )

    controller = _create_controller(
        fake_ai_client=fake_ai_client,
        knowledge_retriever=knowledge_retriever,
        analyzer=setup_components["analyzer"],
        prompt_manager=setup_components["prompt_manager"],
        judge=setup_components["judge"],
    )

    question = "How to reverse engineer this ELF binary?"
    result = controller.process(question)

    assert fake_ai_client.last_prompt is not None

    assert (
        "You are an expert in Reverse Engineering and CTF challenges."
        in fake_ai_client.last_prompt
    )

    assert result.category == Category.REV
    assert result.flag is None


def test_e2e_pipeline_unknown(
    setup_components,
    temp_knowledge_dir: Path,
):
    fake_ai_client = FakeAIClient(
        "I am not sure about this problem."
    )

    knowledge_retriever = KnowledgeRetriever(
        base_dir=temp_knowledge_dir
    )

    controller = _create_controller(
        fake_ai_client=fake_ai_client,
        knowledge_retriever=knowledge_retriever,
        analyzer=setup_components["analyzer"],
        prompt_manager=setup_components["prompt_manager"],
        judge=setup_components["judge"],
    )

    question = "Hello world"
    result = controller.process(question)

    assert fake_ai_client.last_prompt is not None

    assert (
        "You are an expert in Cybersecurity and CTF challenges."
        in fake_ai_client.last_prompt
    )

    assert result.category == Category.UNKNOWN
    assert result.flag is None


def test_e2e_crypto_question_includes_knowledge():
    fake_client = FakeAIClient(
        "The flag is FLAG{crypto_test_flag}"
    )

    controller = _create_controller(
        fake_ai_client=fake_client,
        knowledge_retriever=KnowledgeRetriever(
            base_dir="data/knowledge"
        ),
    )

    result = controller.process(
        "RSA Fermat factorization close primes"
    )

    assert result.category == Category.CRYPTO
    assert fake_client.last_prompt is not None

    assert (
        "Relevant local knowledge:"
        in fake_client.last_prompt
    )

    assert "Fermat" in fake_client.last_prompt


def test_e2e_web_question_no_knowledge_shows_fallback_message():
    fake_client = FakeAIClient("No flag found.")

    controller = _create_controller(
        fake_ai_client=fake_client,
        knowledge_retriever=KnowledgeRetriever(
            base_dir="data/knowledge"
        ),
    )

    controller.process(
        "underwater archaeology dolphin"
    )

    assert fake_client.last_prompt is not None

    assert (
        "No local knowledge available."
        in fake_client.last_prompt
    )


def test_e2e_query_expansion_integration_flow():
    fake_client = FakeAIClient(
        "The flag is FLAG{fermat_expanded_flag}"
    )

    controller = _create_controller(
        fake_ai_client=fake_client,
        knowledge_retriever=KnowledgeRetriever(
            base_dir="data/knowledge"
        ),
    )

    result = controller.process(
        "RSA modulus factors are almost the same size "
        "and very near each other"
    )

    assert result.category == Category.CRYPTO
    assert fake_client.last_prompt is not None

    assert (
        "Relevant local knowledge:"
        in fake_client.last_prompt
    )

    assert "Fermat" in fake_client.last_prompt


def test_e2e_zero_match_query_shows_fallback_message():
    fake_client = FakeAIClient("No flag found.")

    controller = _create_controller(
        fake_ai_client=fake_client,
        knowledge_retriever=KnowledgeRetriever(
            base_dir="data/knowledge"
        ),
    )

    controller.process(
        "quantum spaceship banana"
    )

    assert fake_client.last_prompt is not None

    assert (
        "No local knowledge available."
        in fake_client.last_prompt
    )


def test_e2e_flag_extraction_and_result_correctness():
    fake_client = FakeAIClient(
        "The flag is flag{e2e_answer_generation_success}"
    )

    controller = _create_controller(
        fake_ai_client=fake_client,
        knowledge_retriever=KnowledgeRetriever(
            base_dir="data/knowledge"
        ),
    )

    result = controller.process(
        "Analyze JWT token algorithm none"
    )

    assert result.category == Category.WEB

    assert (
        result.flag
        == "flag{e2e_answer_generation_success}"
    )

    assert result.answer is not None
