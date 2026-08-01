import pytest

from app.analyzer.analyzer import Analyzer
from app.challenge.challenge_input import ChallengeInput
from app.client.base_client import BaseAIClient
from app.controller.controller import Controller
from app.file.file_analysis_result import FileAnalysisResult
from app.judge.confidence_estimator import ConfidenceEstimator
from app.judge.flag_extractor import FlagExtractor
from app.judge.gemini_prompt_generator import GeminiPromptGenerator
from app.judge.hypothesis_extractor import HypothesisExtractor
from app.judge.judge import Judge
from app.judge.next_action_extractor import NextActionExtractor
from app.judge.reason_extractor import ReasonExtractor
from app.knowledge.knowledge_retriever import KnowledgeRetriever
from app.prompt.prompt_manager import PromptManager


class RecordingFakeAIClient(BaseAIClient):
    def __init__(self, response_text: str = "Analysis result") -> None:
        self.response_text = response_text
        self.last_prompt: str | None = None

    def generate(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self.response_text


def _create_controller(
    fake_ai: RecordingFakeAIClient,
) -> Controller:
    judge = Judge(
        flag_extractor=FlagExtractor(),
        confidence_estimator=ConfidenceEstimator(),
        reason_extractor=ReasonExtractor(),
        next_action_extractor=NextActionExtractor(),
        hypothesis_extractor=HypothesisExtractor(),
        gemini_prompt_generator=GeminiPromptGenerator(),
    )

    return Controller(
        analyzer=Analyzer(),
        knowledge_retriever=KnowledgeRetriever(),
        prompt_manager=PromptManager(),
        ai_client=fake_ai,
        judge=judge,
    )


def _make_file_analysis_result(
    name: str = "sample.txt",
    size: int = 100,
    extension: str = ".txt",
    detected_type: str = "text",
    text_content: str | None = "hello world",
    strings: list[str] | None = None,
) -> FileAnalysisResult:
    return FileAnalysisResult(
        name=name,
        size=size,
        extension=extension,
        detected_type=detected_type,
        text_content=text_content,
        strings=strings if strings is not None else ["hello world"],
    )


def test_process_challenge_question_only():
    fake_ai = RecordingFakeAIClient("The answer is 42")
    controller = _create_controller(fake_ai)

    challenge = ChallengeInput(
        question="Decrypt this RSA challenge.",
        files=[],
    )

    result = controller.process_challenge(challenge)

    assert result is not None
    assert fake_ai.last_prompt is not None
    assert "Decrypt this RSA challenge." in fake_ai.last_prompt
    assert "添付ファイル：\nなし" in fake_ai.last_prompt


def test_process_challenge_with_text_file():
    fake_ai = RecordingFakeAIClient("Analyzed text file")
    controller = _create_controller(fake_ai)

    file_result = _make_file_analysis_result(
        name="output.txt",
        text_content="n = 123456789\ne = 65537",
        strings=[
            "n = 123456789",
            "e = 65537",
        ],
    )

    challenge = ChallengeInput(
        question="Solve RSA",
        files=[file_result],
    )

    controller.process_challenge(challenge)

    assert fake_ai.last_prompt is not None
    assert (
        "テキスト内容：\nn = 123456789\ne = 65537"
        in fake_ai.last_prompt
    )


def test_process_challenge_with_binary_file():
    fake_ai = RecordingFakeAIClient("Analyzed binary file")
    controller = _create_controller(fake_ai)

    file_result = _make_file_analysis_result(
        name="challenge.exe",
        detected_type="pe",
        text_content=None,
        strings=[
            "Welcome",
            "FLAG{embedded_test}",
            "Incorrect password",
        ],
    )

    challenge = ChallengeInput(
        question="Reverse this executable",
        files=[file_result],
    )

    controller.process_challenge(challenge)

    assert fake_ai.last_prompt is not None
    assert "検出形式：pe" in fake_ai.last_prompt
    assert "テキスト内容：\n利用できません" in fake_ai.last_prompt
    assert "- FLAG{embedded_test}" in fake_ai.last_prompt


def test_process_challenge_multiple_files():
    fake_ai = RecordingFakeAIClient("Analyzed multiple files")
    controller = _create_controller(fake_ai)

    file1 = _make_file_analysis_result(
        name="file1.txt",
        text_content="content1",
    )

    file2 = _make_file_analysis_result(
        name="file2.bin",
        detected_type="elf",
        text_content=None,
    )

    challenge = ChallengeInput(
        question="Multi file challenge",
        files=[file1, file2],
    )

    controller.process_challenge(challenge)

    assert fake_ai.last_prompt is not None
    assert "[ファイル 1]\nファイル名：file1.txt" in fake_ai.last_prompt
    assert "[ファイル 2]\nファイル名：file2.bin" in fake_ai.last_prompt


def test_analyzer_uses_question_only_for_category():
    fake_ai = RecordingFakeAIClient("OK")
    controller = _create_controller(fake_ai)

    file_result = _make_file_analysis_result(
        strings=[
            "SELECT * FROM users",
            "HTTP/1.1 200 OK",
        ],
    )

    challenge = ChallengeInput(
        question="RSA Fermat factorization",
        files=[file_result],
    )

    result = controller.process_challenge(challenge)

    assert result.category == "Crypto"


def test_knowledge_retriever_uses_question_only():
    fake_ai = RecordingFakeAIClient("OK")
    controller = _create_controller(fake_ai)

    file_result = _make_file_analysis_result(
        strings=["SQL injection payload"],
    )

    challenge = ChallengeInput(
        question="Fermat factorization challenge",
        files=[file_result],
    )

    controller.process_challenge(challenge)

    assert fake_ai.last_prompt is not None
    assert "Fermat" in fake_ai.last_prompt


def test_e2e_flag_extraction_from_file_pipeline():
    fake_ai = RecordingFakeAIClient(
        "The flag is FLAG{file_pipeline_success}"
    )
    controller = _create_controller(fake_ai)

    file_result = FileAnalysisResult(
        name="challenge.exe",
        size=2048,
        extension=".exe",
        detected_type="pe",
        text_content=None,
        strings=[
            "Welcome",
            "FLAG{file_pipeline_success}",
            "Incorrect password",
        ],
    )

    challenge = ChallengeInput(
        question="Find the flag in the attached executable.",
        files=[file_result],
    )

    result = controller.process_challenge(challenge)

    assert fake_ai.last_prompt is not None
    assert "- FLAG{file_pipeline_success}" in fake_ai.last_prompt
    assert result.flag == "FLAG{file_pipeline_success}"


def test_process_challenge_without_flag_hypothesis_handling():
    fake_ai = RecordingFakeAIClient(
        "Hypothesis: Need to bypass anti-debugging.\n"
        "Next Action: Use gdb"
    )
    controller = _create_controller(fake_ai)

    file_result = _make_file_analysis_result(
        name="rev.elf",
        detected_type="elf",
        text_content=None,
    )

    challenge = ChallengeInput(
        question="Reverse elf",
        files=[file_result],
    )

    result = controller.process_challenge(challenge)

    assert result.flag is None
    assert result.hypothesis is not None or result.reason != ""


def test_existing_process_method_backward_compatibility():
    fake_ai = RecordingFakeAIClient(
        "Legacy response FLAG{legacy_pass}"
    )
    controller = _create_controller(fake_ai)

    result = controller.process(
        "RSA Fermat factorization challenge"
    )

    assert fake_ai.last_prompt is not None
    assert "RSA Fermat factorization challenge" in fake_ai.last_prompt
    assert result.flag == "FLAG{legacy_pass}"


def test_empty_question_raises_value_error_from_builder():
    fake_ai = RecordingFakeAIClient("OK")
    controller = _create_controller(fake_ai)

    challenge = ChallengeInput(
        question="",
        files=[],
    )

    with pytest.raises(
        ValueError,
        match="Challenge question cannot be empty.",
    ):
        controller.process_challenge(challenge)
