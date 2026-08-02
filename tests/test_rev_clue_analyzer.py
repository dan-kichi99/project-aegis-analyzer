from pathlib import Path

import pytest

from app.challenge.challenge_context_builder import ChallengeContextBuilder
from app.challenge.challenge_input import ChallengeInput
from app.file.file_input import FileInput
from app.file.rev_clue_analyzer import RevClueAnalyzer
from app.file.static_file_analyzer import StaticFileAnalyzer


def _make_input(name: str, content: bytes) -> FileInput:
    path = Path(name)
    return FileInput(
        name=name,
        path=path,
        size=len(content),
        extension=path.suffix,
        content=content,
    )


def _analyze(*strings: str):
    return RevClueAnalyzer().analyze(list(strings))


def _find(result, value: str):
    return next(clue for clue in result.clues if clue.value == value)


@pytest.mark.parametrize(
    ("value", "category", "severity"),
    [
        ("strcmp", "比較処理", "high"),
        ("memcmp", "比較処理", "high"),
        ("scanf", "入力処理", "medium"),
        ("ReadFile", "入力処理", "medium"),
        ("printf", "出力処理", "low"),
        ("fopen", "ファイル操作", "low"),
        ("malloc", "メモリ操作", "low"),
        ("VirtualAlloc", "メモリ操作", "medium"),
        ("CreateProcessA", "プロセス・実行", "medium"),
        ("IsDebuggerPresent", "アンチデバッグ", "high"),
        ("ptrace", "アンチデバッグ", "high"),
        ("AES", "暗号・ハッシュ", "medium"),
        ("socket", "ネットワーク", "medium"),
    ],
)
def test_classifies_required_function_clues(value, category, severity):
    clue = _find(_analyze(value), value)

    assert clue.category == category
    assert clue.severity == severity
    assert clue.description


@pytest.mark.parametrize(
    ("source", "severity"),
    [
        ("Correct password", "high"),
        ("access granted", "high"),
        ("Wrong key", "medium"),
        ("try again", "medium"),
        ("Enter password:", "medium"),
        ("license invalid", "medium"),
    ],
)
def test_classifies_message_and_secret_clues(source, severity):
    result = _analyze(source)

    assert any(clue.value == source and clue.severity == severity for clue in result.clues)


def test_explicit_flag_has_high_severity():
    clue = _find(_analyze("FLAG{rev_clue}"), "FLAG{rev_clue}")

    assert clue.category == "秘密情報関連"
    assert clue.severity == "high"


@pytest.mark.parametrize(
    "source",
    ["monkey", "my_strcmp_wrapper", "mystrcmphelper", "comparison", "socketpair"],
)
def test_identifier_boundaries_prevent_partial_word_false_positives(source):
    assert _analyze(source).clues == ()


def test_case_insensitive_duplicates_keep_first_value():
    result = _analyze("strcmp", "STRCMP", "StrCmp")

    comparison = [clue for clue in result.clues if clue.category == "比較処理"]
    assert [clue.value for clue in comparison] == ["strcmp"]


def test_results_are_sorted_by_severity_then_source_order():
    result = _analyze("printf", "scanf", "ptrace", "memcmp")

    assert [clue.value for clue in result.clues] == [
        "ptrace",
        "memcmp",
        "scanf",
        "printf",
    ]


def test_result_count_is_limited_to_50():
    sources = [
        "strcmp", "strncmp", "memcmp", "wcscmp", "CompareStringA",
        "CompareStringW", "scanf", "sscanf", "fscanf", "gets", "fgets",
        "getchar", "read", "ReadFile", "GetCommandLineA", "GetCommandLineW",
        "argv", "stdin", "printf", "puts", "putchar", "fprintf", "write",
        "WriteFile", "MessageBoxA", "MessageBoxW", "stdout", "stderr",
        "fopen", "fclose", "fread", "fwrite", "open", "close",
        "CreateFileA", "CreateFileW", "DeleteFileA", "DeleteFileW",
        "GetFileSize", "malloc", "calloc", "realloc", "free", "memcpy",
        "memmove", "memset", "VirtualAlloc", "VirtualProtect", "HeapAlloc",
        "system", "execve", "CreateProcessA", "CreateProcessW", "ShellExecuteA",
        "ShellExecuteW", "LoadLibraryA", "LoadLibraryW", "GetProcAddress",
        "IsDebuggerPresent", "CheckRemoteDebuggerPresent",
        "NtQueryInformationProcess", "ptrace", "DebugActiveProcess",
    ]

    assert len(_analyze(*sources).clues) == 50


def test_analyzer_does_not_modify_source_strings():
    strings = ["strcmp", "printf"]

    RevClueAnalyzer().analyze(strings)

    assert strings == ["strcmp", "printf"]


@pytest.mark.parametrize(
    ("name", "content", "expected"),
    [
        ("sample.exe", b"MZ\x00strcmp\x00", "strcmp"),
        ("sample.elf", b"\x7fELF\x00ptrace\x00", "ptrace"),
    ],
)
def test_static_analyzer_classifies_pe_and_elf_strings(name, content, expected):
    result = StaticFileAnalyzer().analyze(_make_input(name, content))

    assert result.rev_clues is not None
    assert _find(result.rev_clues, expected).value == expected


def test_static_analyzer_does_not_classify_plain_text():
    result = StaticFileAnalyzer().analyze(
        _make_input("sample.txt", b"strcmp and ptrace")
    )

    assert result.rev_clues is None


def test_classification_runs_after_common_encoding_decode():
    result = StaticFileAnalyzer().analyze(
        _make_input("sample.exe", b"MZ\x00c3RyY21w\x00")
    )

    assert "strcmp" in result.strings
    assert result.rev_clues is not None
    assert _find(result.rev_clues, "strcmp").category == "比較処理"


def test_context_builder_displays_rev_clues_in_japanese():
    file_result = StaticFileAnalyzer().analyze(
        _make_input("sample.exe", b"MZ\x00strcmp\x00")
    )
    context = ChallengeContextBuilder().build(
        ChallengeInput(question="Analyze", files=[file_result])
    )

    assert "Rev重要手掛かり：" in context
    assert "[高] strcmp（比較処理）" in context
    assert "入力値や復号結果を期待値と比較" in context


def test_context_builder_omits_empty_rev_clues():
    file_result = StaticFileAnalyzer().analyze(
        _make_input("sample.exe", b"MZ\x00ordinary_string\x00")
    )
    context = ChallengeContextBuilder().build(
        ChallengeInput(question="Analyze", files=[file_result])
    )

    assert "Rev重要手掛かり：" not in context
