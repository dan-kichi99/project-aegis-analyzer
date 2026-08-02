import inspect
from copy import deepcopy

import pytest

from app.agents.agent_input import AgentInput
from app.agents.agent_result import AgentStatus, AgentType
from app.agents.forensics_agent import (
    MAX_CONTEXT_CHARACTERS,
    MAX_EVIDENCE_DETAIL_CHARACTERS,
    MAX_EVIDENCE_ITEMS,
    MAX_KNOWLEDGE_ITEM_CHARACTERS,
    MAX_KNOWLEDGE_ITEMS,
    ForensicsAgent,
)
from app.challenge.challenge_input import ChallengeInput
from app.client.base_client import BaseAIClient
from app.file.appended_data_result import AppendedDataResult
from app.file.file_analysis_result import FileAnalysisResult


class RecordingFakeAIClient(BaseAIClient):
    def __init__(self, response: str = "Forensics AI分析") -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class FailingFakeAIClient(BaseAIClient):
    def generate(self, prompt: str) -> str:
        raise RuntimeError("AI failure")


def _file(name="sample.jpg", detected="png", text="", strings=None, appended=None, size=2048):
    return FileAnalysisResult(name, size, "." + name.rsplit(".", 1)[-1], detected, text, strings or [], appended_data=appended)


def _input(category="Misc", files=None, question="Forensics FLAG{example}", context="Forensics context", knowledge=("ZIP knowledge",), metadata=None):
    return AgentInput(ChallengeInput(question, files or []), category, context, knowledge, metadata or {})


def test_agent_type_and_supported_categories():
    for category in ("Misc", "misc", "Forensics", "FORENSICS"):
        client = RecordingFakeAIClient()
        result = ForensicsAgent(client).analyze(_input(category=category))
        assert result.status is AgentStatus.COMPLETED
        assert len(client.prompts) == 1
    assert ForensicsAgent(RecordingFakeAIClient()).agent_type is AgentType.FORENSICS


@pytest.mark.parametrize("category", ["Crypto", "Rev", "Web", "Unknown"])
def test_other_categories_skip_without_ai(category):
    client = RecordingFakeAIClient()
    result = ForensicsAgent(client).analyze(_input(category=category))
    assert result.status is AgentStatus.SKIPPED
    assert result.answer is None and result.flag_candidate is None
    assert result.evidence == () and client.prompts == []


def test_file_basics_mismatch_unknown_and_small_files_are_safe_evidence():
    result = ForensicsAgent(RecordingFakeAIClient()).analyze(
        _input(files=[_file(), _file("mystery.bin", "unknown", size=0)])
    )
    details = "\n".join(item.detail for item in result.evidence)
    assert "sample.jpg" in details and "拡張子=.jpg" in details
    assert "検出形式=png" in details and "サイズ=2048 bytes" in details
    assert "形式が異なる可能性" in details
    assert "改ざん" not in details
    assert "mystery.bin" in details and "unknown" in details and "0 byte" in details


def test_zip_structure_uses_existing_entry_names_in_order_and_is_limited():
    files = [_file("archive.zip", "zip")]
    files.extend(_file(f"archive.zip::dir/file{index}.txt", "text") for index in range(25))
    result = ForensicsAgent(RecordingFakeAIClient()).analyze(_input(files=files))
    detail = next(item.detail for item in result.evidence if item.source == "zip_structure")
    assert "内部ファイル数=25" in detail
    assert detail.index("file0.txt") < detail.index("file1.txt")
    assert "file20.txt" not in detail


def test_image_metadata_and_forensics_strings_are_selected_without_claiming_origin():
    strings = [
        "ImageDescription: hidden message", "EXIF UserComment author=alice",
        "pcap follow tcp stream", "steganography LSB embedded", "timestamp timezone",
        "RkxBR3tkZWNvZGVkfQ==", "464c41477b6865787d", "ordinary",
    ]
    result = ForensicsAgent(RecordingFakeAIClient()).analyze(_input(files=[_file(strings=strings)]))
    details = "\n".join(item.detail for item in result.evidence)
    for expected in ("ImageDescription", "EXIF", "pcap", "steganography", "LSB", "timestamp", "RkxBR3", "464c"):
        assert expected.casefold() in details.casefold()
    assert "metadata由来です" not in details


def test_appended_data_keeps_offsets_preview_but_not_full_content():
    secret_content = b"full-content-must-not-enter-evidence"
    appended = AppendedDataResult("png", 100, 100, 50, "zip", "PK", "short preview", secret_content)
    result = ForensicsAgent(RecordingFakeAIClient()).analyze(_input(files=[_file(appended=appended)]))
    detail = next(item.detail for item in result.evidence if item.source == "appended_data")
    assert "end_offset=100" in detail and "appended_offset=100" in detail
    assert "detected_type=zip" in detail and "short preview" in detail
    assert secret_content.decode() not in detail


@pytest.mark.parametrize(
    ("file_result", "flag"),
    [
        (_file(text="FLAG{text}"), "FLAG{text}"),
        (_file(strings=["FLAG{strings}"]), "FLAG{strings}"),
        (_file(appended=AppendedDataResult("png", 1, 1, 1, "text", "", "FLAG{preview}", None)), "FLAG{preview}"),
        (_file(appended=AppendedDataResult("png", 1, 1, 1, "text", "", None, b"FLAG{content}")), "FLAG{content}"),
        (_file("archive.zip::flag.txt", "text", text="FLAG{zip}"), "FLAG{zip}"),
    ],
)
def test_local_flag_ordered_sources_skip_ai(file_result, flag):
    client = RecordingFakeAIClient()
    result = ForensicsAgent(client).analyze(_input(files=[file_result]))
    assert result.flag_candidate == flag and result.confidence == 90
    assert client.prompts == []


def test_question_example_flag_is_not_local_candidate():
    client = RecordingFakeAIClient("分析のみ")
    result = ForensicsAgent(client).analyze(_input(question="形式 FLAG{example}"))
    assert result.flag_candidate is None and result.confidence == 40
    assert len(client.prompts) == 1


def test_evidence_priority_limits_and_duplicates():
    appended = AppendedDataResult("png", 1, 1, 2, "zip", "PK", "preview", None)
    files = [_file(text="FLAG{priority}", strings=["metadata hidden"] * 30, appended=appended)]
    result = ForensicsAgent(RecordingFakeAIClient()).analyze(_input(files=files))
    assert len(result.evidence) <= MAX_EVIDENCE_ITEMS
    assert result.evidence[0].source == "local_flag_candidate"
    assert result.evidence[1].source == "appended_data"
    assert all(len(item.detail) <= MAX_EVIDENCE_DETAIL_CHARACTERS for item in result.evidence)
    keys = [(item.source, item.detail) for item in result.evidence]
    assert len(keys) == len(set(keys))


def test_ai_prompt_contains_structured_evidence_and_excludes_sensitive_content():
    client = RecordingFakeAIClient()
    binary = "binary-full-secret"
    appended = AppendedDataResult("png", 10, 10, 5, "zip", "PK", "metadata preview", binary.encode())
    files = [_file("archive.zip", "zip", strings=["pcap hidden timestamp"], appended=appended), _file("archive.zip::inside.txt", "text")]
    ForensicsAgent(client).analyze(_input(files=files, metadata={"OPENAI_API_KEY": "sk-secret"}))
    prompt = client.prompts[0]
    for expected in ("Forensics context", "archive.zip", "zip_structure", "metadata preview", "pcap", "ZIP knowledge", "Respond in Japanese.", "確定事実と仮説", "外部ツールを自動実行せず", "ファイルを実行しない"):
        assert expected in prompt
    assert binary not in prompt and "sk-secret" not in prompt


def test_ai_answer_flag_summary_and_exception_behavior():
    response = "候補 CTF{forensics_ai}" + "説" * 600
    result = ForensicsAgent(RecordingFakeAIClient(response)).analyze(_input())
    assert result.answer == response and len(result.summary) == 500
    assert result.flag_candidate == "CTF{forensics_ai}" and result.confidence == 60
    with pytest.raises(RuntimeError, match="AI failure"):
        ForensicsAgent(FailingFakeAIClient()).analyze(_input())


def test_context_knowledge_limits_and_original_input_unchanged():
    context = "C" * (MAX_CONTEXT_CHARACTERS + 100)
    knowledge = tuple(f"{i}:" + "K" * (MAX_KNOWLEDGE_ITEM_CHARACTERS + 100) for i in range(MAX_KNOWLEDGE_ITEMS + 5))
    agent_input = _input(files=[_file()], context=context, knowledge=knowledge)
    original = deepcopy(agent_input.challenge.files)
    client = RecordingFakeAIClient()
    ForensicsAgent(client).analyze(agent_input)
    assert context[:MAX_CONTEXT_CHARACTERS] in client.prompts[0] and context not in client.prompts[0]
    assert f"{MAX_KNOWLEDGE_ITEMS}:" not in client.prompts[0]
    assert agent_input.context == context and agent_input.local_knowledge == knowledge
    assert agent_input.challenge.files == original


def test_agent_has_no_file_tool_controller_event_or_process_dependency():
    source = inspect.getsource(__import__("app.agents.forensics_agent", fromlist=["*"])).casefold()
    for forbidden in ("subprocess", "controller", "challengeservice", "eventpublisher", "ziparchiveanalyzer", "staticfileanalyzer", "imagemetadataextractor", "open(", "write_text"):
        assert forbidden not in source
