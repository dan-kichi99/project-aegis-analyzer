import inspect
from copy import deepcopy

import pytest

from app.agents.agent_input import AgentInput
from app.agents.agent_result import AgentStatus, AgentType
from app.agents.web_agent import (
    MAX_CONTEXT_CHARACTERS,
    MAX_EVIDENCE_DETAIL_CHARACTERS,
    MAX_EVIDENCE_ITEMS,
    MAX_KNOWLEDGE_ITEM_CHARACTERS,
    MAX_KNOWLEDGE_ITEMS,
    WebAgent,
)
from app.challenge.challenge_input import ChallengeInput
from app.client.base_client import BaseAIClient
from app.file.file_analysis_result import FileAnalysisResult


class RecordingFakeAIClient(BaseAIClient):
    def __init__(self, response: str = "Web AI分析") -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class FailingFakeAIClient(BaseAIClient):
    def generate(self, prompt: str) -> str:
        raise RuntimeError("AI failure")


def _file(text: str, strings: list[str] | None = None) -> FileAnalysisResult:
    return FileAnalysisResult(
        name="request.txt",
        size=len(text),
        extension=".txt",
        detected_type="text",
        text_content=text,
        strings=strings or [],
    )


def _input(
    *,
    category: str = "Web",
    question: str = "Analyze this web challenge",
    files: list[FileAnalysisResult] | None = None,
    context: str = "Web問題コンテキスト",
    knowledge: tuple[str, ...] = ("HTTP knowledge", "SQLi knowledge"),
    metadata=None,
) -> AgentInput:
    return AgentInput(
        ChallengeInput(question, files or []),
        category,
        context,
        knowledge,
        metadata or {},
    )


def test_agent_type_is_web():
    assert WebAgent(RecordingFakeAIClient()).agent_type is AgentType.WEB


@pytest.mark.parametrize("category", ["Crypto", "Rev", "Misc", "Unknown"])
def test_non_web_category_is_skipped_without_ai(category):
    client = RecordingFakeAIClient()
    result = WebAgent(client).analyze(_input(category=category))

    assert result.status is AgentStatus.SKIPPED
    assert result.answer is None
    assert result.flag_candidate is None
    assert result.confidence is None
    assert result.evidence == ()
    assert client.prompts == []


@pytest.mark.parametrize("category", ["Web", "web", "WEB"])
def test_web_category_runs_case_insensitively(category):
    client = RecordingFakeAIClient()
    assert WebAgent(client).analyze(_input(category=category)).status is AgentStatus.COMPLETED
    assert len(client.prompts) == 1


def test_http_requests_responses_headers_and_secrets_become_masked_evidence():
    secret = "must-not-leak"
    text = (
        "POST /login HTTP/1.1\nHost: example.test\n"
        f"Cookie: session={secret}\nAuthorization: Bearer {secret}\n"
        f"Set-Cookie: token={secret}\nContent-Type: application/json\n\n"
        "HTTP/1.1 200 OK"
    )
    result = WebAgent(RecordingFakeAIClient()).analyze(_input(files=[_file(text)]))
    combined = "\n".join(item.detail for item in result.evidence)

    assert "POST /login HTTP/1.1" in combined
    assert "HTTP/1.1 200 OK" in combined
    assert "Host: example.test" in combined
    assert "Content-Type: application/json" in combined
    assert "Cookie: session=[REDACTED]" in combined
    assert "Authorization: [REDACTED]" in combined
    assert "Set-Cookie: token=[REDACTED]" in combined
    assert secret not in combined


def test_urls_endpoints_parameters_and_secret_values_are_extracted_safely():
    text = (
        "GET /admin?id=1&token=secret-token HTTP/1.1\n"
        "Location: https://example.test/api/users?search=test\n"
        "password=secret-password username=alice redirect=/login"
    )
    result = WebAgent(RecordingFakeAIClient()).analyze(_input(files=[_file(text)]))
    evidence = [(item.source, item.detail) for item in result.evidence]
    combined = repr(evidence)

    assert any(source == "url_endpoint" and "/admin" in detail for source, detail in evidence)
    assert any(source == "url_endpoint" and "https://example.test" in detail for source, detail in evidence)
    assert any(source == "parameter" and "id=1" in detail for source, detail in evidence)
    assert "password=[REDACTED]" in combined
    assert "token=[REDACTED]" in combined
    assert "secret-password" not in combined
    assert "secret-token" not in combined


@pytest.mark.parametrize(
    "technology",
    ["PHP", "Flask", "nginx", "MySQL", "JWT", "PostgreSQL", "Jinja2"],
)
def test_web_technologies_are_evidence(technology):
    result = WebAgent(RecordingFakeAIClient()).analyze(
        _input(files=[_file(f"Server uses {technology}")])
    )
    assert any(item.source == "web_technology" and item.detail == technology for item in result.evidence)


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("UNION SELECT password FROM users SQL syntax", "SQL Injection"),
        ("<script>alert(1)</script>", "XSS"),
        ("{{7*7}} Jinja2", "SSTI"),
        ("file=../../etc/passwd", "LFI"),
        ("../../secret", "Path Traversal"),
        ("cmd=whoami && whoami", "Command Injection"),
        ("url=http://127.0.0.1/admin", "SSRF"),
        ("Possible IDOR user_id=2", "IDOR"),
        ("multipart/form-data upload", "Insecure File Upload"),
    ],
)
def test_vulnerability_candidates_are_non_confirming_evidence(text, name):
    result = WebAgent(RecordingFakeAIClient()).analyze(_input(files=[_file(text)]))
    details = [item.detail for item in result.evidence if item.source == "vulnerability_candidate"]

    assert any(name in detail for detail in details)
    assert all("可能性" in detail for detail in details)
    assert all("脆弱性を確認しました" not in detail for detail in details)


def test_evidence_priority_deduplication_and_limits():
    text = "\n".join(
        ["FLAG{priority}", "UNION SELECT password FROM users", "Cookie: x=y"]
        + [f"https://example.test/api/{index}?id={index}" for index in range(30)]
        + ["PHP Flask Django nginx MySQL PostgreSQL SQLite JWT"]
    )
    result = WebAgent(RecordingFakeAIClient()).analyze(_input(files=[_file(text, [text])]))

    assert len(result.evidence) <= MAX_EVIDENCE_ITEMS
    assert result.evidence[0].source == "local_flag_candidate"
    assert all(len(item.detail) <= MAX_EVIDENCE_DETAIL_CHARACTERS for item in result.evidence)
    keys = [(item.source, item.detail.casefold()) for item in result.evidence]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ([_file("FLAG{text_content}")], "FLAG{text_content}"),
        ([_file("none", ["FLAG{strings}"])], "FLAG{strings}"),
    ],
)
def test_attachment_flags_skip_ai_and_have_local_confidence(files, expected):
    client = RecordingFakeAIClient()
    result = WebAgent(client).analyze(_input(files=files))

    assert result.flag_candidate == expected
    assert result.confidence == 90
    assert client.prompts == []


def test_question_example_flag_is_not_a_local_candidate():
    client = RecordingFakeAIClient("分析のみ")
    result = WebAgent(client).analyze(_input(question="形式例 FLAG{example}"))

    assert result.flag_candidate is None
    assert result.confidence == 40
    assert len(client.prompts) == 1


def test_ai_is_called_once_with_masked_structured_prompt():
    client = RecordingFakeAIClient()
    secret = "private-cookie-value"
    context = (
        "GET /api/users?id=1 HTTP/1.1\n"
        f"Cookie: session={secret}\nAuthorization: Bearer {secret}\n"
        "Flask nginx MySQL UNION SELECT"
    )
    agent_input = _input(context=context, files=[_file(context)])

    WebAgent(client).analyze(agent_input)

    assert len(client.prompts) == 1
    prompt = client.prompts[0]
    assert "/api/users" in prompt and "id=1" in prompt
    assert "Flask" in prompt and "nginx" in prompt and "MySQL" in prompt
    assert "SQL Injection" in prompt
    assert "HTTP knowledge" in prompt
    assert "Respond in Japanese." in prompt
    assert "確定事実と仮説" in prompt
    assert "外部サイトへアクセスせず" in prompt
    assert secret not in prompt
    assert "[REDACTED]" in prompt


def test_metadata_and_api_key_are_not_added_to_prompt():
    client = RecordingFakeAIClient()
    WebAgent(client).analyze(
        _input(metadata={"OPENAI_API_KEY": "sk-secret", "other": "hidden-metadata"})
    )
    assert "sk-secret" not in client.prompts[0]
    assert "hidden-metadata" not in client.prompts[0]


def test_ai_answer_flag_summary_confidence_and_no_flag_path():
    response = "候補 CTF{web_ai}" + "説" * 600
    result = WebAgent(RecordingFakeAIClient(response)).analyze(_input())
    assert result.answer == response
    assert len(result.summary) == 500
    assert result.flag_candidate == "CTF{web_ai}"
    assert result.confidence == 60
    assert result.confidence < 90

    without_flag = WebAgent(RecordingFakeAIClient("分析案のみ")).analyze(_input())
    assert without_flag.status is AgentStatus.COMPLETED
    assert without_flag.flag_candidate is None
    assert without_flag.confidence == 40


def test_ai_exception_propagates_without_retry():
    with pytest.raises(RuntimeError, match="AI failure"):
        WebAgent(FailingFakeAIClient()).analyze(_input())


def test_context_knowledge_limits_and_original_input_immutability():
    context = "C" * (MAX_CONTEXT_CHARACTERS + 100)
    knowledge = tuple(
        f"{index}:" + "K" * (MAX_KNOWLEDGE_ITEM_CHARACTERS + 100)
        for index in range(MAX_KNOWLEDGE_ITEMS + 5)
    )
    agent_input = _input(context=context, knowledge=knowledge, files=[_file("GET / HTTP/1.1")])
    original_files = deepcopy(agent_input.challenge.files)
    client = RecordingFakeAIClient()

    WebAgent(client).analyze(agent_input)

    assert context[:MAX_CONTEXT_CHARACTERS] in client.prompts[0]
    assert context not in client.prompts[0]
    assert f"{MAX_KNOWLEDGE_ITEMS}:" not in client.prompts[0]
    assert agent_input.context == context
    assert agent_input.local_knowledge == knowledge
    assert agent_input.challenge.files == original_files


def test_web_agent_has_no_network_browser_controller_event_or_process_dependency():
    source = inspect.getsource(
        __import__("app.agents.web_agent", fromlist=["*"])
    ).casefold()
    for forbidden in (
        "requests", "socket", "subprocess", "controller", "challengeservice",
        "eventpublisher", "selenium", "playwright", "webbrowser", "curl", "wget",
    ):
        assert forbidden not in source
