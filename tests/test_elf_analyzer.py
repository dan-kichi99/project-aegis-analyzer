import struct
from pathlib import Path

import pytest

from app.challenge.challenge_context_builder import ChallengeContextBuilder
from app.challenge.challenge_input import ChallengeInput
from app.file.elf_analyzer import ElfAnalyzer
from app.file.file_analysis_result import FileAnalysisResult
from app.file.file_input import FileInput
from app.file.static_file_analyzer import StaticFileAnalyzer


def make_elf(
    *,
    elf64: bool = True,
    big_endian: bool = False,
    machine: int | None = None,
    file_type: int = 2,
    include_interpreter: bool = True,
) -> bytes:
    endian = ">" if big_endian else "<"
    elf_class = 2 if elf64 else 1
    header_size = 64 if elf64 else 52
    program_size = 56 if elf64 else 32
    section_size = 64 if elf64 else 40
    program_count = 2 if include_interpreter else 1
    section_count = 3
    program_offset = header_size
    section_offset = 0x200
    entry_point = 0x401000 if elf64 else 0x8048000
    machine = machine if machine is not None else (62 if elf64 else 3)
    content = bytearray(0x400)
    content[:4] = b"\x7fELF"
    content[4] = elf_class
    content[5] = 2 if big_endian else 1
    content[6] = 1

    if elf64:
        struct.pack_into(
            f"{endian}HHIQQQIHHHHHH",
            content,
            16,
            file_type,
            machine,
            1,
            entry_point,
            program_offset,
            section_offset,
            0xA5,
            header_size,
            program_size,
            program_count,
            section_size,
            section_count,
            2,
        )
    else:
        struct.pack_into(
            f"{endian}HHIIIIIHHHHHH",
            content,
            16,
            file_type,
            machine,
            1,
            entry_point,
            program_offset,
            section_offset,
            0xA5,
            header_size,
            program_size,
            program_count,
            section_size,
            section_count,
            2,
        )

    interpreter = b"/lib64/ld-linux-x86-64.so.2\x00"
    content[0x100 : 0x100 + len(interpreter)] = interpreter
    for index in range(program_count):
        start = program_offset + index * program_size
        if index == 0:
            values = (1, 5, 0, 0x400000, 0, 0x400, 0x400, 0x1000)
        else:
            values = (
                3,
                4,
                0x100,
                0x400100,
                0,
                len(interpreter),
                len(interpreter),
                1,
            )
        segment_type, flags, offset, va, pa, file_size, memory_size, align = values
        if elf64:
            struct.pack_into(
                f"{endian}IIQQQQQQ",
                content,
                start,
                segment_type,
                flags,
                offset,
                va,
                pa,
                file_size,
                memory_size,
                align,
            )
        else:
            struct.pack_into(
                f"{endian}IIIIIIII",
                content,
                start,
                segment_type,
                offset,
                va,
                pa,
                file_size,
                memory_size,
                flags,
                align,
            )

    string_table = b"\x00.text\x00.bss\x00.shstrtab\x00"
    content[0x300 : 0x300 + len(string_table)] = string_table
    sections = [
        (1, 1, 0x6, 0x401000, 0x180, 0x10),
        (7, 8, 0x3, 0x402000, 0x500, 0x100),
        (12, 3, 0, 0, 0x300, len(string_table)),
    ]
    marker = b"preserved_text"
    content[0x180 : 0x180 + len(marker)] = marker
    for index, values in enumerate(sections):
        start = section_offset + index * section_size
        name, section_type, flags, va, offset, size = values
        if elf64:
            struct.pack_into(
                f"{endian}IIQQQQIIQQ",
                content,
                start,
                name,
                section_type,
                flags,
                va,
                offset,
                size,
                0,
                0,
                1,
                0,
            )
        else:
            struct.pack_into(
                f"{endian}IIIIIIIIII",
                content,
                start,
                name,
                section_type,
                flags,
                va,
                offset,
                size,
                0,
                0,
                1,
                0,
            )
    return bytes(content)


def make_input(content: bytes, name: str = "sample.elf") -> FileInput:
    return FileInput(
        name=name,
        path=Path(name),
        size=len(content),
        extension=Path(name).suffix,
        content=content,
    )


def analyze(content: bytes):
    return ElfAnalyzer().analyze(make_input(content))


@pytest.mark.parametrize(
    ("elf64", "big_endian", "expected_class", "expected_endian"),
    [
        (False, False, "ELF32", "little-endian"),
        (True, False, "ELF64", "little-endian"),
        (False, True, "ELF32", "big-endian"),
        (True, True, "ELF64", "big-endian"),
    ],
)
def test_parses_classes_and_endianness(
    elf64,
    big_endian,
    expected_class,
    expected_endian,
):
    result = analyze(make_elf(elf64=elf64, big_endian=big_endian))

    assert result is not None
    assert result.elf_class == expected_class
    assert result.endianness == expected_endian


@pytest.mark.parametrize(
    ("machine", "expected"),
    [
        (3, "x86"),
        (62, "x86-64"),
        (40, "ARM"),
        (183, "ARM64"),
        (8, "MIPS"),
        (243, "RISC-V"),
        (0xFFFF, "unknown"),
    ],
)
def test_maps_architectures(machine, expected):
    result = analyze(make_elf(machine=machine))

    assert result is not None
    assert result.architecture == expected


def test_reads_entry_point_and_executable_type():
    result = analyze(make_elf())

    assert result is not None
    assert result.entry_point == 0x401000
    assert result.file_type == "Executable"


def test_shared_object_is_not_overclassified():
    result = analyze(make_elf(file_type=3))

    assert result is not None
    assert result.file_type == "Shared Object / PIE候補"


def test_reads_program_headers_and_interpreter():
    result = analyze(make_elf())

    assert result is not None
    assert [segment.segment_type for segment in result.segments] == [
        "PT_LOAD",
        "PT_INTERP",
    ]
    assert result.interpreter == "/lib64/ld-linux-x86-64.so.2"


def test_segment_permissions_are_decoded():
    result = analyze(make_elf())

    assert result is not None
    segment = result.segments[0]
    assert segment.readable is True
    assert segment.writable is False
    assert segment.executable is True


def test_reads_section_names_types_and_permissions():
    result = analyze(make_elf())

    assert result is not None
    assert [section.name for section in result.sections] == [
        ".text",
        ".bss",
        ".shstrtab",
    ]
    text = result.sections[0]
    assert text.section_type == "SHT_PROGBITS"
    assert text.allocatable is True
    assert text.writable is False
    assert text.executable is True


def test_nobits_section_is_valid_without_file_data():
    result = analyze(make_elf())

    assert result is not None
    bss = result.sections[1]
    assert bss.section_type == "SHT_NOBITS"
    assert bss.data_in_bounds is True


def test_invalid_magic_fails_safely():
    content = bytearray(make_elf())
    content[:4] = b"NOPE"

    assert analyze(bytes(content)) is None


@pytest.mark.parametrize(("index", "value"), [(4, 3), (5, 3)])
def test_invalid_class_or_endian_fails_safely(index, value):
    content = bytearray(make_elf())
    content[index] = value

    assert analyze(bytes(content)) is None


def test_short_header_fails_safely():
    assert analyze(b"\x7fELF\x02\x01\x01") is None


@pytest.mark.parametrize(("offset", "is_64"), [(32, True), (28, False)])
def test_program_header_out_of_range_fails_safely(offset, is_64):
    content = bytearray(make_elf(elf64=is_64))
    endian = "<"
    format_code = "Q" if is_64 else "I"
    struct.pack_into(f"{endian}{format_code}", content, offset, 0x10000)

    assert analyze(bytes(content)) is None


@pytest.mark.parametrize(("offset", "is_64"), [(40, True), (32, False)])
def test_section_header_out_of_range_fails_safely(offset, is_64):
    content = bytearray(make_elf(elf64=is_64))
    format_code = "Q" if is_64 else "I"
    struct.pack_into(f"<{format_code}", content, offset, 0x10000)

    assert analyze(bytes(content)) is None


@pytest.mark.parametrize(("offset", "value"), [(56, 129), (60, 257)])
def test_excessive_header_counts_fail_safely(offset, value):
    content = bytearray(make_elf())
    struct.pack_into("<H", content, offset, value)

    assert analyze(bytes(content)) is None


def test_out_of_range_string_table_does_not_raise():
    content = bytearray(make_elf())
    section_three = 0x200 + 2 * 64
    struct.pack_into("<Q", content, section_three + 24, 0x10000)

    result = analyze(bytes(content))

    assert result is not None
    assert all(section.name == "" for section in result.sections)


def test_non_elf_does_not_get_elf_analysis():
    result = StaticFileAnalyzer().analyze(make_input(b"ordinary text", "a.txt"))

    assert result.elf_info is None


def test_static_analyzer_preserves_strings_for_elf():
    result = StaticFileAnalyzer().analyze(make_input(make_elf()))

    assert result.elf_info is not None
    assert "preserved_text" in result.strings


def test_context_builder_includes_elf_information():
    file_result = StaticFileAnalyzer().analyze(make_input(make_elf()))
    context = ChallengeContextBuilder().build(
        ChallengeInput(question="Analyze ELF", files=[file_result])
    )

    assert "ELF解析：" in context
    assert "- 形式：ELF64" in context
    assert "- エンディアン：little-endian" in context
    assert "- アーキテクチャ：x86-64" in context
    assert "- 種別：Executable" in context
    assert "- EntryPoint：0x401000" in context
    assert "- Interpreter：/lib64/ld-linux-x86-64.so.2" in context
    assert "- PT_LOAD Offset=0x0" in context
    assert "- .text Type=SHT_PROGBITS" in context


def test_context_builder_omits_elf_information_when_absent():
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

    assert "ELF解析：" not in context


def test_pe_detection_is_not_affected():
    result = StaticFileAnalyzer().analyze(make_input(b"MZ\x00\x00", "a.exe"))

    assert result.detected_type == "pe"
    assert result.elf_info is None
