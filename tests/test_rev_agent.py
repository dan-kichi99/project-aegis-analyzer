import inspect
from copy import deepcopy

import pytest

from app.agents.agent_input import AgentInput
from app.agents.agent_result import AgentStatus, AgentType
from app.agents.rev_agent import (
    MAX_CONTEXT_CHARACTERS,
    MAX_EVIDENCE_DETAIL_CHARACTERS,
    MAX_EVIDENCE_ITEMS,
    MAX_KNOWLEDGE_ITEM_CHARACTERS,
    MAX_KNOWLEDGE_ITEMS,
    RevAgent,
)
from app.challenge.challenge_input import ChallengeInput
from app.client.base_client import BaseAIClient
from app.file.appended_data_result import AppendedDataResult
from app.file.elf_analysis_result import ElfAnalysisResult, ElfSection, ElfSegment
from app.file.file_analysis_result import FileAnalysisResult
from app.file.pe_analysis_result import PeAnalysisResult, PeSection
from app.file.rev_clue_result import RevClue, RevClueResult


class RecordingFakeAIClient(BaseAIClient):
    def __init__(self, response: str = "Rev AI分析") -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class FailingFakeAIClient(BaseAIClient):
    def generate(self, prompt: str) -> str:
        raise RuntimeError("AI failure")


def _pe() -> PeAnalysisResult:
    return PeAnalysisResult(
        valid_signature=True,
        format="PE32+",
        architecture="x86-64",
        number_of_sections=2,
        timestamp=0,
        entry_point_rva=0x1000,
        image_base=0x140000000,
        section_alignment=0x1000,
        file_alignment=0x200,
        subsystem="Windows CUI",
        kind="executable",
        sections=(
            PeSection(
                ".text", 100, 0x1000, 100, 0x400, 0, True, False, True, True
            ),
            PeSection(
                ".wxc", 100, 0x2000, 100, 0x800, 0, True, True, True, False
            ),
        ),
    )


def _elf() -> ElfAnalysisResult:
    return ElfAnalysisResult(
        valid_signature=True,
        elf_class="ELF64",
        endianness="little",
        architecture="x86-64",
        file_type="executable",
        entry_point=0x401000,
        program_header_offset=64,
        section_header_offset=512,
        program_header_count=1,
        section_header_count=1,
        flags=0,
        interpreter="/lib64/ld-linux.so.2",
        sections=(
            ElfSection(
                ".danger", "PROGBITS", 0, 0x401000, 512, 100, True, True, True, False
            ),
        ),
        segments=(
            ElfSegment("LOAD", 0, 0x400000, 100, 100, 7, 4096, True, True, True, False),
        ),
    )


def _file(
    *,
    text: str = "binary text",
    strings: list[str] | None = None,
    pe=True,
    elf=True,
    clues: tuple[RevClue, ...] | None = None,
    appended: AppendedDataResult | None = None,
) -> FileAnalysisResult:
    return FileAnalysisResult(
        name="challenge.bin",
        size=1024,
        extension=".bin",
        detected_type="binary",
        text_content=text,
        strings=strings or ["strcmp", "Enter password", "ordinary filler"],
        pe_info=_pe() if pe else None,
        elf_info=_elf() if elf else None,
        rev_clues=RevClueResult(
            clues
            or (
                RevClue("printf", "出力処理", "output", "low"),
                RevClue("strcmp", "比較処理", "compare", "high"),
                RevClue("scanf", "入力処理", "input", "medium"),
            )
        ),
        appended_data=appended,
    )


def _input(
    *,
    category: str = "Rev",
    files: list[FileAnalysisResult] | None = None,
    context: str = "Rev問題コンテキスト",
    knowledge: tuple[str, ...] = ("PE knowledge", "ELF knowledge"),
    metadata=None,
) -> AgentInput:
    return AgentInput(
        ChallengeInput("Reverse this binary", files or []),
        category,
        context,
        knowledge,
        metadata or {},
    )


def test_agent_type_is_rev():
    assert RevAgent(RecordingFakeAIClient()).agent_type is AgentType.REV


@pytest.mark.parametrize("category", ["Crypto", "Web", "Misc", "Unknown"])
def test_non_rev_category_is_skipped_without_ai(category):
    client = RecordingFakeAIClient()

    result = RevAgent(client).analyze(_input(category=category))

    assert result.status is AgentStatus.SKIPPED
    assert result.answer is None
    assert result.flag_candidate is None
    assert result.confidence is None
    assert result.evidence == ()
    assert result.next_actions == ()
    assert result.error_message is None
    assert client.prompts == []


@pytest.mark.parametrize("category", ["Rev", "rev", "REV"])
def test_rev_category_uses_current_analyzer_value_case_insensitively(category):
    client = RecordingFakeAIClient()

    result = RevAgent(client).analyze(_input(category=category))

    assert result.status is AgentStatus.COMPLETED
    assert len(client.prompts) == 1


def test_pe_and_elf_structure_anomalies_become_evidence():
    result = RevAgent(RecordingFakeAIClient()).analyze(_input(files=[_file()]))
    evidence = {item.source: item for item in result.evidence}

    assert "format=PE32+" in evidence["pe:challenge.bin"].detail
    assert "architecture=x86-64" in evidence["pe:challenge.bin"].detail
    assert ".text" in evidence["pe_sections:challenge.bin"].detail
    assert ".wxc" in evidence["pe_sections:challenge.bin"].detail
    assert "W=True,X=True" in evidence["pe_sections:challenge.bin"].detail
    assert "raw_in_bounds=False" in evidence["pe_sections:challenge.bin"].detail
    assert "elf_class=ELF64" in evidence["elf:challenge.bin"].detail
    assert "interpreter=/lib64/ld-linux.so.2" in evidence["elf:challenge.bin"].detail
    assert "LOAD" in evidence["elf_segments:challenge.bin"].detail
    assert "W=True,X=True" in evidence["elf_segments:challenge.bin"].detail
    assert "data_in_bounds=False" in evidence["elf_sections:challenge.bin"].detail


def test_rev_clues_are_sorted_by_severity_stably_with_confidence_mapping():
    clues = (
        RevClue("low-first", "low", "one", "low"),
        RevClue("high-first", "high", "two", "high"),
        RevClue("medium-first", "medium", "three", "medium"),
        RevClue("high-second", "high", "four", "high"),
    )
    result = RevAgent(RecordingFakeAIClient()).analyze(
        _input(files=[_file(pe=False, elf=False, clues=clues, strings=[])])
    )
    clue_evidence = [item for item in result.evidence if item.source.startswith("rev_clue")]

    assert ["value=high-first" in item.detail for item in clue_evidence] == [
        True,
        False,
        False,
        False,
    ]
    assert [item.confidence for item in clue_evidence] == [85, 85, 65, 40]
    assert "value=high-second" in clue_evidence[1].detail
    assert "value=medium-first" in clue_evidence[2].detail
    assert "value=low-first" in clue_evidence[3].detail


def test_appended_data_and_pe_overlay_are_separate_evidence():
    appended = AppendedDataResult(
        "pe", 100, 100, 20, "zip", "PK", "overlay preview", b"overlay"
    )
    result = RevAgent(RecordingFakeAIClient()).analyze(
        _input(files=[_file(elf=False, appended=appended)])
    )
    sources = [item.source for item in result.evidence]

    assert "appended_data:challenge.bin" in sources
    assert "pe_overlay:challenge.bin" in sources
    assert any("preview=overlay preview" in item.detail for item in result.evidence)


def test_important_strings_are_selected_and_clue_duplicates_are_suppressed():
    strings = [
        "strcmp",
        "password=secret",
        "https://example.test/path",
        "IsDebuggerPresent",
        "ordinary filler",
    ]
    result = RevAgent(RecordingFakeAIClient()).analyze(
        _input(files=[_file(pe=False, elf=False, strings=strings)])
    )
    details = [
        item.detail for item in result.evidence if item.source.startswith("important_string")
    ]

    assert "strcmp" not in details
    assert "ordinary filler" not in details
    assert "password=secret" in details
    assert "https://example.test/path" in details
    assert "IsDebuggerPresent" in details
    assert len(details) <= 10


def test_evidence_limits_keep_structural_and_high_priority_information():
    clues = tuple(
        RevClue(f"high-{index}", "comparison", "D" * 700, "high")
        for index in range(30)
    )
    files = [_file(clues=clues, strings=[f"password-{index}" for index in range(30)])]

    result = RevAgent(RecordingFakeAIClient()).analyze(_input(files=files))

    assert len(result.evidence) <= MAX_EVIDENCE_ITEMS
    assert all(len(item.detail) <= MAX_EVIDENCE_DETAIL_CHARACTERS for item in result.evidence)
    assert result.evidence[0].source.startswith("pe:")
    assert any("value=high-0" in item.detail for item in result.evidence)


@pytest.mark.parametrize(
    ("file_result", "expected"),
    [
        (_file(text="FLAG{text}", pe=False, elf=False, strings=[]), "FLAG{text}"),
        (_file(text="none", pe=False, elf=False, strings=["FLAG{strings}"]), "FLAG{strings}"),
        (
            _file(
                text="none",
                pe=False,
                elf=False,
                strings=[],
                appended=AppendedDataResult(
                    "raw", 1, 1, 10, "text", "", "FLAG{appended}", None
                ),
            ),
            "FLAG{appended}",
        ),
    ],
)
def test_local_flag_sources_are_detected_without_ai(file_result, expected):
    client = RecordingFakeAIClient()

    result = RevAgent(client).analyze(_input(files=[file_result]))

    assert result.flag_candidate == expected
    assert result.confidence == 90
    assert client.prompts == []


def test_local_flag_priority_and_duplicate_suppression_starts_with_rev_clue():
    file_result = _file(
        pe=False,
        elf=False,
        text="FLAG{text} FLAG{same}",
        strings=["FLAG{strings}", "FLAG{same}"],
        clues=(
            RevClue("FLAG{clue}", "secret", "candidate", "high"),
            RevClue("FLAG{same}", "secret", "duplicate", "high"),
        ),
        appended=AppendedDataResult(
            "raw", 1, 1, 1, "text", "", "FLAG{append} FLAG{same}", None
        ),
    )

    result = RevAgent(RecordingFakeAIClient()).analyze(_input(files=[file_result]))

    assert result.flag_candidate == "FLAG{clue}"


def test_without_local_flag_ai_is_called_once_with_structured_prompt():
    client = RecordingFakeAIClient()
    agent_input = _input(
        files=[
            _file(
                appended=AppendedDataResult(
                    "pe", 100, 100, 20, "zip", "PK", "overlay", b"overlay"
                )
            )
        ]
    )

    RevAgent(client).analyze(agent_input)

    assert len(client.prompts) == 1
    prompt = client.prompts[0]
    assert agent_input.context in prompt
    assert "PE32+" in prompt
    assert "ELF64" in prompt
    assert "strcmp" in prompt
    assert "password" in prompt
    assert "appended_data" in prompt
    assert "PE knowledge" in prompt and "ELF knowledge" in prompt
    assert "Respond in Japanese." in prompt
    assert "確定事実と仮説" in prompt
    assert "Flag候補を正解と断定しない" in prompt
    assert "Section・Segment" in prompt


def test_metadata_api_key_and_binary_content_are_not_in_prompt():
    client = RecordingFakeAIClient()
    secret = "sk-rev-secret"
    binary_marker = "full-binary-must-not-appear"
    file_result = _file(
        appended=AppendedDataResult(
            "raw", 1, 1, 10, "binary", "", None, binary_marker.encode()
        )
    )

    RevAgent(client).analyze(
        _input(
            files=[file_result],
            metadata={"OPENAI_API_KEY": secret, "metadata": "hidden"},
        )
    )

    prompt = client.prompts[0]
    assert secret not in prompt
    assert "OPENAI_API_KEY" not in prompt
    assert "hidden" not in prompt
    assert binary_marker not in prompt


def test_ai_response_answer_flag_confidence_and_summary():
    response = "解析回答 CTF{rev_ai}" + "説" * 600

    result = RevAgent(RecordingFakeAIClient(response)).analyze(_input())

    assert result.answer == response
    assert len(result.summary) == 500
    assert result.flag_candidate == "CTF{rev_ai}"
    assert result.confidence == 60
    assert result.confidence < 90
    assert result.evidence[-1].source == "ai_analysis"


def test_ai_response_without_flag_is_completed():
    result = RevAgent(RecordingFakeAIClient("解析方針のみ")).analyze(_input())

    assert result.status is AgentStatus.COMPLETED
    assert result.flag_candidate is None
    assert result.confidence == 40


def test_ai_exception_propagates_without_retry():
    with pytest.raises(RuntimeError, match="AI failure"):
        RevAgent(FailingFakeAIClient()).analyze(_input())


def test_context_and_knowledge_limits_do_not_modify_original_input():
    context = "C" * (MAX_CONTEXT_CHARACTERS + 100)
    knowledge = tuple(
        f"{index}:" + "K" * (MAX_KNOWLEDGE_ITEM_CHARACTERS + 100)
        for index in range(MAX_KNOWLEDGE_ITEMS + 5)
    )
    agent_input = _input(context=context, knowledge=knowledge, files=[_file()])
    original_files = deepcopy(agent_input.challenge.files)
    client = RecordingFakeAIClient()

    RevAgent(client).analyze(agent_input)

    prompt = client.prompts[0]
    assert context[:MAX_CONTEXT_CHARACTERS] in prompt
    assert context not in prompt
    assert f"{MAX_KNOWLEDGE_ITEMS}:" not in prompt
    assert agent_input.context == context
    assert agent_input.local_knowledge == knowledge
    assert agent_input.challenge.files == original_files


def test_rev_agent_has_no_controller_execution_event_or_subprocess_dependency():
    source = inspect.getsource(
        __import__("app.agents.rev_agent", fromlist=["*"])
    ).casefold()

    assert "controller" not in source
    assert "challengeservice" not in source
    assert "eventpublisher" not in source
    assert "subprocess" not in source
    assert "pythonexecutionrunner" not in source
