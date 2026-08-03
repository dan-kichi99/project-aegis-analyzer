from dataclasses import fields
from pathlib import Path

import pytest

from app.file.file_analysis_result import FileAnalysisResult
from app.file.file_input import FileInput
from app.file.rev_clue_analyzer import RevClueAnalyzer
from app.file.static_file_analyzer import StaticFileAnalyzer
from app.judge.flag_extractor import FlagExtractor


def _input(content: bytes, name: str = "sample.bin") -> FileInput:
    path = Path(name)
    return FileInput(name, path, len(content), path.suffix, content)


def _analyze(content: bytes, name: str = "sample.bin") -> FileAnalysisResult:
    return StaticFileAnalyzer().analyze(_input(content, name))


def _clue_values(result: FileAnalysisResult) -> set[str]:
    assert result.rev_clues is not None
    return {clue.value for clue in result.rev_clues.clues}


def test_extracts_ascii_and_utf16le_strings_without_controls():
    utf16 = "UTF16_FLAG{wide}".encode("utf-16-le")
    result = _analyze(b"MZ\x00ASCII_FLAG{plain}\x00" + utf16 + b"\x01")
    assert "ASCII_FLAG{plain}" in result.strings
    assert "UTF16_FLAG{wide}" in result.strings
    assert all(
        all(char.isprintable() for char in value) for value in result.strings
    )


@pytest.mark.parametrize(
    ("magic", "expected"),
    [
        (b"\x7fELF", "elf"),
        (b"MZ", "pe"),
        (b"\xcf\xfa\xed\xfe", "mach-o"),
        (b"\xfe\xed\xfa\xce", "mach-o"),
    ],
)
def test_detects_executable_formats(magic: bytes, expected: str):
    assert _analyze(magic + b"\x00ordinary", "program.bin").detected_type == expected


@pytest.mark.parametrize(
    "marker",
    ["UPX!", "PyInstaller", "Go build", "runtime.main", "Rust", "rust_eh_personality", "GCC", "MSVC", "clang", "Nuitka"],
)
def test_detects_compiler_runtime_and_packer_traces(marker: str):
    result = _analyze(b"MZ\x00" + marker.encode() + b"\x00", "program.exe")
    assert result.rev_clues is not None
    expected = marker.rstrip("!")
    assert any(
        clue.category == "Compiler / Packer" and expected in clue.value
        for clue in result.rev_clues.clues
    )


@pytest.mark.parametrize(
    "section",
    [".text", ".data", ".rdata", ".rodata", ".bss", ".idata", ".eh_frame", ".pydata", ".upx"],
)
def test_detects_known_section_names(section: str):
    result = _analyze(b"MZ\x00" + section.encode() + b"\x00", "sections.exe")
    assert any(
        clue.value.casefold() == section.casefold() and clue.category == "Section"
        for clue in (result.rev_clues.clues if result.rev_clues else ())
    )


@pytest.mark.parametrize(
    "symbol",
    [
        "printf", "puts", "scanf", "gets", "system", "CreateFile",
        "ReadFile", "WriteFile", "VirtualAlloc", "WinExec", "ShellExecute",
        "socket", "connect", "recv", "send", "execve", "fork",
    ],
)
def test_detects_required_import_or_export_symbol_candidates(symbol: str):
    result = _analyze(b"MZ\x00" + symbol.encode() + b"\x00", "imports.exe")
    assert symbol in _clue_values(result)


@pytest.mark.parametrize(
    "marker",
    ["IsDebuggerPresent", "ptrace", "PDB", "debug_assert", "assertion_failed"],
)
def test_detects_debug_strings(marker: str):
    result = _analyze(b"\x7fELF\x00" + marker.encode() + b"\x00", "debug.elf")
    assert marker in _clue_values(result)


@pytest.mark.parametrize(
    "flag",
    [
        "FLAG{x}", "CTF{x}", "picoCTF{x}", "HTB{x}", "DUCTF{x}",
        "AIS3{x}", "SECCON{x}", "TSGCTF{x}", "TCP1P{x}",
    ],
)
def test_flag_detection_reuses_the_existing_extractor(flag: str):
    assert FlagExtractor().extract(flag) == flag
    result = RevClueAnalyzer().analyze([flag])
    clue = next(item for item in result.clues if item.value == flag)
    assert clue.severity == "high"


def test_empty_large_and_long_inputs_are_bounded():
    empty = _analyze(b"")
    assert empty.strings == []
    assert empty.rev_clues is None

    content = b"MZ\x00" + b"".join(
        f"value_{index:04d}\x00".encode() for index in range(700)
    )
    bounded = _analyze(content, "large.exe")
    assert len(bounded.strings) == 500

    long_value = _analyze(b"A" * 1_000)
    assert len(long_value.strings) == 1
    assert len(long_value.strings[0]) == 300


def test_source_dto_and_public_file_result_shape_remain_unchanged():
    file_input = _input(b"MZ\x00printf\x00", "stable.exe")
    before = (file_input.name, file_input.path, file_input.size, file_input.content)
    result = StaticFileAnalyzer().analyze(file_input)
    assert before == (file_input.name, file_input.path, file_input.size, file_input.content)
    assert [field.name for field in fields(FileAnalysisResult)] == [
        "name", "size", "extension", "detected_type", "text_content",
        "strings", "pe_info", "elf_info", "rev_clues", "xor_result",
        "caesar_result", "appended_data", "recursive_encoding_result",
    ]
    assert result.name == "stable.exe"


def test_analysis_modules_have_no_ai_execution_network_or_external_tool_calls():
    source = "".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "app/file/static_file_analyzer.py",
            "app/file/rev_clue_analyzer.py",
            "app/file/file_type_detector.py",
        )
    )
    for forbidden in (
        "subprocess", "socket.", "requests", "OpenAI", "os.system",
        "\nexec(", "\neval(", "shell=True", "Controller",
    ):
        assert forbidden not in source


def test_existing_file_analysis_result_constructor_is_backward_compatible():
    result = FileAnalysisResult("x", 0, ".bin", "unknown", None, [])
    assert result.strings == []
    assert result.rev_clues is None
