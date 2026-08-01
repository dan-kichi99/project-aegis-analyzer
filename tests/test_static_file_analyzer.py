from pathlib import Path

from app.file.file_input import FileInput
from app.file.static_file_analyzer import StaticFileAnalyzer


def _make_file_input(name: str, content: bytes) -> FileInput:
    path = Path(name)
    return FileInput(
        name=name,
        path=path,
        size=len(content),
        extension=path.suffix,
        content=content,
    )


def test_analyze_text_file():
    file_input = _make_file_input("challenge.txt", b"RSA challenge text")
    analyzer = StaticFileAnalyzer()

    result = analyzer.analyze(file_input)

    assert result.detected_type == "text"
    assert result.text_content == "RSA challenge text"
    assert "RSA challenge text" in result.strings


def test_analyze_pe_binary():
    file_input = _make_file_input("sample.exe", b"MZ\x90\x00\x03\x00Hello_World")
    analyzer = StaticFileAnalyzer()

    result = analyzer.analyze(file_input)

    assert result.detected_type == "pe"
    assert result.text_content is None
    assert "Hello_World" in result.strings


def test_analyze_elf_strings():
    file_input = _make_file_input("sample.elf", b"\x7fELF\x02\x01\x01\x00FLAG{elf_test_flag}")
    analyzer = StaticFileAnalyzer()

    result = analyzer.analyze(file_input)

    assert result.detected_type == "elf"
    assert "FLAG{elf_test_flag}" in result.strings


def test_printable_strings_minimum_length():
    file_input = _make_file_input("test.bin", b"\x00abc\x00abcd\x00")
    analyzer = StaticFileAnalyzer()

    result = analyzer.analyze(file_input)

    assert "abc" not in result.strings
    assert "abcd" in result.strings


def test_multiple_strings_extraction():
    file_input = _make_file_input("test.bin", b"first_string\x00second_string")
    analyzer = StaticFileAnalyzer()

    result = analyzer.analyze(file_input)

    assert result.strings == ["first_string", "second_string"]


def test_nul_delimited_strings():
    file_input = _make_file_input("test.bin", b"\x00FLAG{test}\x00hello\x01abc")
    analyzer = StaticFileAnalyzer()

    result = analyzer.analyze(file_input)

    assert result.strings == ["FLAG{test}", "hello"]


def test_unknown_binary_strings():
    file_input = _make_file_input("unknown.bin", b"\x00\xff\x00some_readable_text\x00\xfe")
    analyzer = StaticFileAnalyzer()

    result = analyzer.analyze(file_input)

    assert result.detected_type == "unknown"
    assert "some_readable_text" in result.strings


def test_empty_file():
    file_input = _make_file_input("empty.dat", b"")
    analyzer = StaticFileAnalyzer()

    result = analyzer.analyze(file_input)

    assert result.detected_type == "empty"
    assert result.text_content is None
    assert result.strings == []


def test_max_strings_limit():
    content = b"".join(f"string_{i:04d}\x00".encode("ascii") for i in range(300))
    file_input = _make_file_input("many_strings.bin", content)
    analyzer = StaticFileAnalyzer()

    result = analyzer.analyze(file_input)

    assert len(result.strings) == 200
    assert result.strings[0] == "string_0000"
    assert result.strings[199] == "string_0199"


def test_analysis_byte_limit():
    padding = b"\x00" * 2_000_000
    file_input = _make_file_input("large.bin", padding + b"hidden_at_the_end_beyond_limit")
    analyzer = StaticFileAnalyzer()

    result = analyzer.analyze(file_input)

    assert "hidden_at_the_end_beyond_limit" not in result.strings


def test_fake_extension_png():
    file_input = _make_file_input("image.txt", b"\x89PNG\r\n\x1a\n\x00\x00\x00embedded_png_string")
    analyzer = StaticFileAnalyzer()

    result = analyzer.analyze(file_input)

    assert result.detected_type == "png"
    assert result.text_content is None
    assert "embedded_png_string" in result.strings


test_japanese_text_content = "RSA暗号の解読問題"


def test_japanese_text():
    file_input = _make_file_input("japanese.txt", test_japanese_text_content.encode("utf-8"))
    analyzer = StaticFileAnalyzer()

    result = analyzer.analyze(file_input)

    assert result.detected_type == "text"
    assert result.text_content == test_japanese_text_content
