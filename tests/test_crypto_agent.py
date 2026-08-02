import inspect
from copy import deepcopy

import pytest

from app.agents.agent_input import AgentInput
from app.agents.agent_result import AgentStatus, AgentType
from app.agents.crypto_agent import (
    MAX_CONTEXT_CHARACTERS,
    MAX_EVIDENCE_DETAIL_CHARACTERS,
    MAX_EVIDENCE_ITEMS,
    MAX_KNOWLEDGE_ITEM_CHARACTERS,
    MAX_KNOWLEDGE_ITEMS,
    MAX_KNOWLEDGE_TOTAL_CHARACTERS,
    CryptoAgent,
)
from app.challenge.challenge_input import ChallengeInput
from app.client.base_client import BaseAIClient
from app.file.file_analysis_result import FileAnalysisResult
from app.solver.caesar_result import CaesarCandidate, CaesarResult
from app.solver.rsa_result import RsaAttempt, RsaParameters, RsaResult
from app.solver.xor_result import SingleByteXorResult, XorCandidate


class RecordingFakeAIClient(BaseAIClient):
    def __init__(self, response: str = "AIによる暗号分析") -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class FailingFakeAIClient(BaseAIClient):
    def generate(self, prompt: str) -> str:
        raise RuntimeError("AI failure")


def _rsa(plaintext: str | None = None) -> RsaResult:
    contains_flag = plaintext is not None and "FLAG{" in plaintext
    return RsaResult(
        parameters=RsaParameters(
            n=3233,
            e=17,
            c=855,
            p=61,
            q=53,
            d=2753,
            phi=3120,
            source="question",
        ),
        attempts=(
            RsaAttempt(
                method="provided_factors",
                success=plaintext is not None,
                detail="used p and q",
                plaintext=plaintext,
                contains_flag=contains_flag,
            ),
        ),
        plaintext=plaintext,
        contains_flag=contains_flag,
    )


def _file(
    *,
    xor_plaintext: str = "decoded xor text",
    caesar_plaintext: str = "decoded caesar text",
) -> FileAnalysisResult:
    return FileAnalysisResult(
        name="crypto.txt",
        size=10,
        extension=".txt",
        detected_type="text",
        text_content="ciphertext material",
        strings=["encoded string"],
        xor_result=SingleByteXorResult(
            candidates=(
                XorCandidate(
                    key=42,
                    plaintext=xor_plaintext,
                    score=9.5,
                    contains_flag="FLAG{" in xor_plaintext,
                    source="text_content",
                ),
            )
        ),
        caesar_result=CaesarResult(
            candidates=(
                CaesarCandidate(
                    shift=13,
                    plaintext=caesar_plaintext,
                    score=8.0,
                    contains_flag="FLAG{" in caesar_plaintext,
                    source="strings",
                ),
            )
        ),
    )


def _input(
    *,
    category: str = "Crypto",
    rsa: RsaResult | None = None,
    files: list[FileAnalysisResult] | None = None,
    context: str = "問題文と添付ファイルのCryptoコンテキスト",
    knowledge: tuple[str, ...] = ("RSA knowledge", "XOR knowledge"),
    metadata=None,
) -> AgentInput:
    return AgentInput(
        challenge=ChallengeInput(
            question="RSA challenge",
            files=files or [],
            rsa_result=rsa,
        ),
        category=category,
        context=context,
        local_knowledge=knowledge,
        metadata=metadata or {},
    )


def test_agent_type_is_always_crypto():
    assert CryptoAgent(RecordingFakeAIClient()).agent_type is AgentType.CRYPTO


@pytest.mark.parametrize("category", ["Web", "Rev", "Misc", "Unknown"])
def test_non_crypto_category_is_skipped_without_ai(category):
    ai_client = RecordingFakeAIClient()

    result = CryptoAgent(ai_client).analyze(_input(category=category))

    assert result.status is AgentStatus.SKIPPED
    assert result.answer is None
    assert result.flag_candidate is None
    assert result.confidence is None
    assert result.evidence == ()
    assert result.next_actions == ()
    assert result.error_message is None
    assert ai_client.prompts == []


@pytest.mark.parametrize("category", ["Crypto", "crypto", "CRYPTO"])
def test_crypto_category_uses_current_analyzer_value_case_insensitively(category):
    ai_client = RecordingFakeAIClient()

    result = CryptoAgent(ai_client).analyze(_input(category=category))

    assert result.status is AgentStatus.COMPLETED
    assert len(ai_client.prompts) == 1


def test_rsa_xor_caesar_and_file_material_become_ordered_evidence():
    result = CryptoAgent(RecordingFakeAIClient()).analyze(
        _input(rsa=_rsa(), files=[_file()])
    )

    sources = [item.source for item in result.evidence]
    assert sources == [
        "rsa_parameters",
        "rsa_attempt",
        "text:crypto.txt",
        "strings:crypto.txt",
        "xor:crypto.txt",
        "caesar:crypto.txt",
        "ai_analysis",
    ]
    assert "n=3233" in result.evidence[0].detail
    assert "method=provided_factors" in result.evidence[1].detail
    assert "key=42" in result.evidence[4].detail
    assert "shift=13" in result.evidence[5].detail


def test_all_evidence_details_and_count_are_limited():
    files = [_file(xor_plaintext="x" * 2_000) for _ in range(30)]

    result = CryptoAgent(RecordingFakeAIClient()).analyze(_input(files=files))

    assert len(result.evidence) <= MAX_EVIDENCE_ITEMS
    assert all(
        len(item.detail) <= MAX_EVIDENCE_DETAIL_CHARACTERS
        for item in result.evidence
    )


@pytest.mark.parametrize(
    ("rsa_flag", "xor_flag", "caesar_flag", "expected"),
    [
        ("FLAG{rsa}", "FLAG{xor}", "FLAG{caesar}", "FLAG{rsa}"),
        (None, "FLAG{xor}", "FLAG{caesar}", "FLAG{xor}"),
        (None, "plain xor", "FLAG{caesar}", "FLAG{caesar}"),
    ],
)
def test_local_flag_priority_is_rsa_then_xor_then_caesar(
    rsa_flag,
    xor_flag,
    caesar_flag,
    expected,
):
    ai_client = RecordingFakeAIClient()
    result = CryptoAgent(ai_client).analyze(
        _input(
            rsa=_rsa(rsa_flag) if rsa_flag else None,
            files=[_file(xor_plaintext=xor_flag, caesar_plaintext=caesar_flag)],
        )
    )

    assert result.flag_candidate == expected
    assert result.confidence == 90
    assert result.status is AgentStatus.COMPLETED
    assert ai_client.prompts == []


def test_duplicate_local_flags_are_not_repeated_or_sent_to_ai():
    ai_client = RecordingFakeAIClient()
    result = CryptoAgent(ai_client).analyze(
        _input(
            rsa=_rsa("FLAG{same}"),
            files=[_file(xor_plaintext="FLAG{same}", caesar_plaintext="FLAG{same}")],
        )
    )

    assert result.flag_candidate == "FLAG{same}"
    assert ai_client.prompts == []


def test_without_local_flag_ai_is_called_exactly_once_and_prompt_is_structured():
    ai_client = RecordingFakeAIClient()
    agent_input = _input(rsa=_rsa(), files=[_file()])

    result = CryptoAgent(ai_client).analyze(agent_input)

    assert result.status is AgentStatus.COMPLETED
    assert len(ai_client.prompts) == 1
    prompt = ai_client.prompts[0]
    assert agent_input.context in prompt
    assert "RSA knowledge" in prompt
    assert "XOR knowledge" in prompt
    assert "n=3233" in prompt
    assert "key=42" in prompt
    assert "shift=13" in prompt
    assert "Respond in Japanese." in prompt
    assert "確定事実と仮説" in prompt
    assert "Flag候補を正解と断定しない" in prompt
    assert "コード・数式・暗号パラメータを改変しない" in prompt


def test_metadata_and_api_key_are_not_copied_to_prompt():
    ai_client = RecordingFakeAIClient()
    secret = "sk-must-not-enter-prompt"

    CryptoAgent(ai_client).analyze(
        _input(metadata={"OPENAI_API_KEY": secret, "arbitrary": "metadata-value"})
    )

    assert secret not in ai_client.prompts[0]
    assert "metadata-value" not in ai_client.prompts[0]
    assert "OPENAI_API_KEY" not in ai_client.prompts[0]


def test_ai_response_is_preserved_and_flag_uses_existing_extractor():
    response = "分析結果です。候補は CTF{ai_candidate} です。"
    result = CryptoAgent(RecordingFakeAIClient(response)).analyze(_input())

    assert result.answer == response
    assert result.summary == response
    assert result.flag_candidate == "CTF{ai_candidate}"
    assert result.confidence == 60
    assert result.confidence < 90
    assert result.evidence[-1].source == "ai_analysis"


def test_ai_response_without_flag_is_completed_with_analysis_confidence():
    result = CryptoAgent(RecordingFakeAIClient("仮説のみです。")).analyze(_input())

    assert result.status is AgentStatus.COMPLETED
    assert result.flag_candidate is None
    assert result.confidence == 40


def test_ai_summary_is_limited_but_answer_is_preserved():
    response = "分" * 800
    result = CryptoAgent(RecordingFakeAIClient(response)).analyze(_input())

    assert len(result.summary) == 500
    assert result.answer == response


def test_ai_exception_propagates_without_retry():
    with pytest.raises(RuntimeError, match="AI failure"):
        CryptoAgent(FailingFakeAIClient()).analyze(_input())


def test_knowledge_and_context_limits_apply_only_to_prompt_copy():
    context = "C" * (MAX_CONTEXT_CHARACTERS + 100)
    knowledge = tuple(
        f"{index}:" + "K" * (MAX_KNOWLEDGE_ITEM_CHARACTERS + 100)
        for index in range(MAX_KNOWLEDGE_ITEMS + 5)
    )
    agent_input = _input(context=context, knowledge=knowledge)
    ai_client = RecordingFakeAIClient()

    CryptoAgent(ai_client).analyze(agent_input)

    prompt = ai_client.prompts[0]
    assert context[:MAX_CONTEXT_CHARACTERS] in prompt
    assert context not in prompt
    assert f"{MAX_KNOWLEDGE_ITEMS}:" not in prompt
    included = [item[:MAX_KNOWLEDGE_ITEM_CHARACTERS] for item in knowledge[:10]]
    assert sum(len(item) for item in included) >= MAX_KNOWLEDGE_TOTAL_CHARACTERS
    assert agent_input.context == context
    assert agent_input.local_knowledge == knowledge


def test_original_agent_and_challenge_input_are_not_modified():
    agent_input = _input(rsa=_rsa(), files=[_file()])
    original_question = agent_input.challenge.question
    original_files = deepcopy(agent_input.challenge.files)

    CryptoAgent(RecordingFakeAIClient()).analyze(agent_input)

    assert agent_input.challenge.question == original_question
    assert agent_input.challenge.files == original_files


def test_crypto_agent_has_no_controller_event_execution_or_process_dependency():
    source = inspect.getsource(
        __import__("app.agents.crypto_agent", fromlist=["*"])
    ).casefold()

    assert "controller" not in source
    assert "challengeservice" not in source
    assert "eventpublisher" not in source
    assert "subprocess" not in source
    assert "pythonexecutionrunner" not in source
