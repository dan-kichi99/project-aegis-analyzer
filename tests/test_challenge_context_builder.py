import pytest

from app.challenge.challenge_context_builder import ChallengeContextBuilder
from app.challenge.challenge_input import ChallengeInput
from app.file.file_analysis_result import FileAnalysisResult


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


def test_question_only():
    builder = ChallengeContextBuilder()
    challenge = ChallengeInput(question="Decrypt this RSA challenge.", files=[])

    result = builder.build(challenge)

    expected = "Challenge Question:\nDecrypt this RSA challenge.\n\nAttached Files:\nNone"
    assert result == expected


def test_question_and_single_text_file():
    builder = ChallengeContextBuilder()
    file_res = _make_file_analysis_result(
        name="output.txt",
        size=124,
        extension=".txt",
        detected_type="text",
        text_content="c = 12345",
        strings=["c = 12345"],
    )
    challenge = ChallengeInput(
        question="Find flag.",
        files=[file_res],
    )

    result = builder.build(challenge)

    assert "Challenge Question:\nFind flag." in result
    assert "[File 1]\nName: output.txt" in result
    assert "Text Content:\nc = 12345" in result
    assert "Extracted Strings:\n- c = 12345" in result


def test_question_and_single_binary_file():
    builder = ChallengeContextBuilder()
    file_res = _make_file_analysis_result(
        name="sample.exe",
        size=2048,
        extension=".exe",
        detected_type="pe",
        text_content=None,
        strings=["MZ_header", "FLAG{binary_flag}"],
    )
    challenge = ChallengeInput(
        question="Reverse this executable.",
        files=[file_res],
    )

    result = builder.build(challenge)

    assert "Detected Type: pe" in result
    assert "Text Content:\nNot available" in result
    assert "Extracted Strings:\n- MZ_header\n- FLAG{binary_flag}" in result


def test_multiple_files_and_order_preservation():
    builder = ChallengeContextBuilder()
    file1 = _make_file_analysis_result(name="first.txt")
    file2 = _make_file_analysis_result(name="second.bin", detected_type="unknown", text_content=None)
    challenge = ChallengeInput(
        question="Analyze these files.",
        files=[file1, file2],
    )

    result = builder.build(challenge)

    assert "[File 1]\nName: first.txt" in result
    assert "[File 2]\nName: second.bin" in result
    assert result.index("[File 1]") < result.index("[File 2]")


def test_text_content_none():
    builder = ChallengeContextBuilder()
    file_res = _make_file_analysis_result(text_content=None)
    challenge = ChallengeInput(question="Test question.", files=[file_res])

    result = builder.build(challenge)

    assert "Text Content:\nNot available" in result


def test_strings_empty():
    builder = ChallengeContextBuilder()
    file_res = _make_file_analysis_result(strings=[])
    challenge = ChallengeInput(question="Test question.", files=[file_res])

    result = builder.build(challenge)

    assert "Extracted Strings:\nNone" in result


def test_strings_limit_50():
    builder = ChallengeContextBuilder()
    many_strings = [f"str_{i}" for i in range(100)]
    file_res = _make_file_analysis_result(strings=many_strings)
    challenge = ChallengeInput(question="Test question.", files=[file_res])

    result = builder.build(challenge)

    assert "- str_0" in result
    assert "- str_49" in result
    assert "- str_50" not in result
    # 元の FileAnalysisResult の strings 自体は変更されないことの検証
    assert len(file_res.strings) == 100


def test_text_content_limit_10000():
    builder = ChallengeContextBuilder()
    long_text = "A" * 15_000
    file_res = _make_file_analysis_result(text_content=long_text)
    challenge = ChallengeInput(question="Test question.", files=[file_res])

    result = builder.build(challenge)

    assert "A" * 10_000 + "\n[truncated]" in result
    assert "A" * 10_001 not in result
    # 元の FileAnalysisResult の text_content 自体は変更されないことの検証
    assert len(file_res.text_content) == 15_000


def test_empty_question_raises_value_error():
    builder = ChallengeContextBuilder()
    challenge = ChallengeInput(question="", files=[])

    with pytest.raises(ValueError, match="Challenge question cannot be empty."):
        builder.build(challenge)


def test_whitespace_question_raises_value_error():
    builder = ChallengeContextBuilder()
    challenge = ChallengeInput(question="   \n\t  ", files=[])

    with pytest.raises(ValueError, match="Challenge question cannot be empty."):
        builder.build(challenge)


def test_japanese_question():
    builder = ChallengeContextBuilder()
    challenge = ChallengeInput(question="この暗号文を解読してください。", files=[])

    result = builder.build(challenge)

    assert "Challenge Question:\nこの暗号文を解読してください。" in result


def test_japanese_text_content():
    builder = ChallengeContextBuilder()
    file_res = _make_file_analysis_result(
        name="japanese.txt",
        text_content="フラグは FLAG{日本語テスト} です。",
        strings=["FLAG{日本語テスト}"],
    )
    challenge = ChallengeInput(question="問題文", files=[file_res])

    result = builder.build(challenge)

    assert "Text Content:\nフラグは FLAG{日本語テスト} です。" in result
    assert "- FLAG{日本語テスト}" in result
