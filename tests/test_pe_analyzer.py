import struct
from pathlib import Path

import pytest

from app.challenge.challenge_context_builder import ChallengeContextBuilder
from app.challenge.challenge_input import ChallengeInput
from app.file.file_analysis_result import FileAnalysisResult
from app.file.file_input import FileInput
from app.file.pe_analyzer import PeAnalyzer
from app.file.static_file_analyzer import StaticFileAnalyzer


def make_pe(
    *,
    pe_plus: bool = False,
    machine: int | None = None,
    dll: bool = False,
    sections: list[tuple[str, int]] | None = None,
) -> bytes:
    pe_offset = 0x80
    optional_size = 0xF0 if pe_plus else 0xE0
    machine = machine if machine is not None else (0x8664 if pe_plus else 0x014C)
    sections = sections or [(".text", 0x60000020)]
    characteristics = 0x0002 | (0x2000 if dll else 0)

    content = bytearray(pe_offset + 24 + optional_size + len(sections) * 40)
    content[:2] = b"MZ"
    struct.pack_into("<I", content, 0x3C, pe_offset)
    content[pe_offset : pe_offset + 4] = b"PE\x00\x00"
    struct.pack_into(
        "<HHIIIHH",
        content,
        pe_offset + 4,
        machine,
        len(sections),
        0x12345678,
        0,
        0,
        optional_size,
        characteristics,
    )
    optional_offset = pe_offset + 24
    struct.pack_into(
        "<H", content, optional_offset, 0x20B if pe_plus else 0x10B
    )
    struct.pack_into("<I", content, optional_offset + 16, 0x1000)
    if pe_plus:
        struct.pack_into("<Q", content, optional_offset + 24, 0x140000000)
    else:
        struct.pack_into("<I", content, optional_offset + 28, 0x400000)
    struct.pack_into("<I", content, optional_offset + 32, 0x1000)
    struct.pack_into("<I", content, optional_offset + 36, 0x200)
    struct.pack_into("<H", content, optional_offset + 68, 3)

    section_offset = optional_offset + optional_size
    raw_offset = 0x400
    for index, (name, section_characteristics) in enumerate(sections):
        current = section_offset + index * 40
        content[current : current + 8] = name.encode()[:8].ljust(8, b"\x00")
        struct.pack_into(
            "<IIII",
            content,
            current + 8,
            0x500,
            0x1000 + index * 0x1000,
            0x200,
            raw_offset + index * 0x200,
        )
        struct.pack_into("<I", content, current + 36, section_characteristics)

    required_size = raw_offset + len(sections) * 0x200
    content.extend(b"\x00" * max(0, required_size - len(content)))
    content[raw_offset : raw_offset + 15] = b"preserved_text"
    return bytes(content)


def make_input(content: bytes, name: str = "sample.exe") -> FileInput:
    return FileInput(
        name=name,
        path=Path(name),
        size=len(content),
        extension=Path(name).suffix,
        content=content,
    )


def analyze_pe(content: bytes):
    return PeAnalyzer().analyze(make_input(content))


def test_parses_valid_pe32():
    result = analyze_pe(make_pe())

    assert result is not None
    assert result.valid_signature is True
    assert result.format == "PE32"


def test_parses_valid_pe32_plus():
    result = analyze_pe(make_pe(pe_plus=True))

    assert result is not None
    assert result.format == "PE32+"


@pytest.mark.parametrize(
    ("machine", "expected"),
    [
        (0x014C, "x86"),
        (0x8664, "x86-64"),
        (0x01C4, "ARM"),
        (0xAA64, "ARM64"),
        (0xFFFF, "unknown"),
    ],
)
def test_maps_supported_machine_architectures(machine, expected):
    result = analyze_pe(make_pe(machine=machine))

    assert result is not None
    assert result.architecture == expected


def test_reads_entry_point_and_pe32_image_base():
    result = analyze_pe(make_pe())

    assert result is not None
    assert result.entry_point_rva == 0x1000
    assert result.image_base == 0x400000


def test_reads_pe32_plus_image_base():
    result = analyze_pe(make_pe(pe_plus=True))

    assert result is not None
    assert result.image_base == 0x140000000


@pytest.mark.parametrize(("dll", "expected"), [(False, "EXE"), (True, "DLL")])
def test_distinguishes_exe_and_dll(dll, expected):
    result = analyze_pe(make_pe(dll=dll))

    assert result is not None
    assert result.kind == expected


def test_reads_section_name_and_permissions():
    result = analyze_pe(make_pe(sections=[(".data", 0xC0000040)]))

    assert result is not None
    section = result.sections[0]
    assert section.name == ".data"
    assert section.readable is True
    assert section.writable is True
    assert section.executable is False


def test_preserves_multiple_section_order():
    result = analyze_pe(
        make_pe(
            sections=[
                (".text", 0x60000020),
                (".rdata", 0x40000040),
                (".data", 0xC0000040),
            ]
        )
    )

    assert result is not None
    assert [section.name for section in result.sections] == [
        ".text",
        ".rdata",
        ".data",
    ]


def test_out_of_range_e_lfanew_fails_safely():
    content = bytearray(64)
    content[:2] = b"MZ"
    struct.pack_into("<I", content, 0x3C, 0x1000)

    assert analyze_pe(bytes(content)) is None


def test_invalid_pe_signature_fails_safely():
    content = bytearray(make_pe())
    content[0x80 : 0x84] = b"NOPE"

    assert analyze_pe(bytes(content)) is None


def test_short_optional_header_fails_safely():
    content = bytearray(make_pe())
    struct.pack_into("<H", content, 0x80 + 4 + 16, 10)

    assert analyze_pe(bytes(content)) is None


def test_truncated_section_table_fails_safely():
    content = make_pe()[: 0x80 + 24 + 0xE0 + 20]

    assert analyze_pe(content) is None


def test_excessive_section_count_fails_safely():
    content = bytearray(make_pe())
    struct.pack_into("<H", content, 0x80 + 6, 97)

    assert analyze_pe(bytes(content)) is None


def test_non_pe_does_not_get_pe_analysis():
    result = StaticFileAnalyzer().analyze(make_input(b"ordinary text", "a.txt"))

    assert result.detected_type == "text"
    assert result.pe_info is None


def test_static_analyzer_preserves_strings_for_pe():
    result = StaticFileAnalyzer().analyze(make_input(make_pe()))

    assert result.pe_info is not None
    assert "preserved_text" in result.strings


def test_context_builder_includes_japanese_pe_information():
    file_result = StaticFileAnalyzer().analyze(
        make_input(make_pe(pe_plus=True), "sample.exe")
    )
    context = ChallengeContextBuilder().build(
        ChallengeInput(question="Analyze PE", files=[file_result])
    )

    assert "PE解析：" in context
    assert "- 形式：PE32+" in context
    assert "- アーキテクチャ：x86-64" in context
    assert "- EntryPoint RVA：0x1000" in context
    assert "- ImageBase：0x140000000" in context
    assert "- Subsystem：Windows CUI" in context
    assert "- 種別：EXE" in context
    assert "- .text RVA=0x1000" in context
    assert "RX" in context


def test_context_builder_omits_pe_section_for_other_files():
    file_result = FileAnalysisResult(
        name="plain.txt",
        size=4,
        extension=".txt",
        detected_type="text",
        text_content="data",
        strings=["data"],
    )
    context = ChallengeContextBuilder().build(
        ChallengeInput(question="Analyze", files=[file_result])
    )

    assert "PE解析：" not in context
