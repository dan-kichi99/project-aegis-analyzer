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

    expected = "問題文：\nDecrypt this RSA challenge.\n\n添付ファイル：\nなし"
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

    assert "問題文：\nFind flag." in result
    assert "添付ファイル：" in result
    assert "[ファイル 1]\nファイル名：output.txt" in result
    assert "テキスト内容：\nc = 12345" in result
    assert "抽出文字列：\n- c = 12345" in result


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

    assert "検出形式：pe" in result
    assert "テキスト内容：\n利用できません" in result
    assert "抽出文字列：\n- MZ_header\n- FLAG{binary_flag}" in result


def test_multiple_files_and_order_preservation():
    builder = ChallengeContextBuilder()
    file1 = _make_file_analysis_result(name="first.txt")
    file2 = _make_file_analysis_result(name="second.bin", detected_type="unknown", text_content=None)
    challenge = ChallengeInput(
        question="Analyze these files.",
        files=[file1, file2],
    )

    result = builder.build(challenge)

    assert "[ファイル 1]\nファイル名：first.txt" in result
    assert "[ファイル 2]\nファイル名：second.bin" in result
    assert result.index("[ファイル 1]") < result.index("[ファイル 2]")


def test_text_content_none():
    builder = ChallengeContextBuilder()
    file_res = _make_file_analysis_result(text_content=None)
    challenge = ChallengeInput(question="Test question.", files=[file_res])

    result = builder.build(challenge)

    assert "テキスト内容：\n利用できません" in result


def test_strings_empty():
    builder = ChallengeContextBuilder()
    file_res = _make_file_analysis_result(strings=[])
    challenge = ChallengeInput(question="Test question.", files=[file_res])

    result = builder.build(challenge)

    assert "抽出文字列：\nなし" in result


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

    assert "A" * 10_000 + "\n[省略]" in result
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

    assert "問題文：\nこの暗号文を解読してください。" in result


def test_japanese_text_content():
    builder = ChallengeContextBuilder()
    file_res = _make_file_analysis_result(
        name="japanese.txt",
        text_content="フラグは FLAG{日本語テスト} です。",
        strings=["FLAG{日本語テスト}"],
    )
    challenge = ChallengeInput(question="問題文", files=[file_res])

    result = builder.build(challenge)

    assert "テキスト内容：\nフラグは FLAG{日本語テスト} です。" in result
    assert "- FLAG{日本語テスト}" in result
