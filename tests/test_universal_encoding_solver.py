import base64
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.challenge.challenge_input import ChallengeInput
from app.challenge.challenge_service import ChallengeService
from app.file.file_analysis_result import FileAnalysisResult
from app.solver.universal_encoding_analyzer import (
    MAX_UNIVERSAL_ENCODING_DEPTH,
    MAX_UNIVERSAL_ENCODING_SOURCES,
    UniversalEncodingAnalyzer,
)
from app.solver.universal_encoding_result import MAX_UNIVERSAL_ENCODING_STEPS
from app.solver.universal_encoding_solver import (
    MAX_UNIVERSAL_ENCODING_INPUT,
    UniversalEncodingSolver,
)


def _file(
    name: str,
    *,
    text_content: str | None = None,
    strings: list[str] | None = None,
) -> FileAnalysisResult:
    return FileAnalysisResult(
        name=name,
        size=len(text_content or ""),
        extension=Path(name).suffix,
        detected_type="text",
        text_content=text_content,
        strings=list(strings or []),
    )


def _analyze(value: str):
    return UniversalEncodingAnalyzer().analyze(ChallengeInput(value))


@pytest.mark.parametrize(
    ("method", "encoded", "plain"),
    [
        ("base32", base64.b32encode(b"FLAG{base32}").decode(), "FLAG{base32}"),
        ("base85", base64.b85encode(b"FLAG{base85}").decode(), "FLAG{base85}"),
        ("ascii85", base64.a85encode(b"FLAG{ascii85}").decode(), "FLAG{ascii85}"),
        ("ascii85", base64.a85encode(b"FLAG{adobe}", adobe=True).decode(), "FLAG{adobe}"),
        ("hex_ascii", b"FLAG{hex}".hex(), "FLAG{hex}"),
        (
            "binary_ascii",
            " ".join(f"{byte:08b}" for byte in b"FLAG{binary}"),
            "FLAG{binary}",
        ),
        (
            "octal_ascii",
            " ".join(f"{byte:03o}" for byte in b"FLAG{octal}"),
            "FLAG{octal}",
        ),
        (
            "decimal_ascii",
            ", ".join(str(byte) for byte in b"FLAG{decimal}"),
            "FLAG{decimal}",
        ),
    ],
)
def test_supported_encodings_decode_to_flag(method: str, encoded: str, plain: str):
    result = _analyze(encoded)
    assert result is not None
    assert plain in result.flag_candidates
    assert any(step.method == method and step.output_preview == plain for step in result.steps)


def test_lowercase_unpadded_base32_and_spaced_hex_are_supported():
    base32 = base64.b32encode(b"FLAG{lower}").decode().rstrip("=").lower()
    hex_value = " ".join(f"{byte:02x}" for byte in b"FLAG{spaced_hex}")
    assert "FLAG{lower}" in _analyze(base32).flag_candidates
    assert "FLAG{spaced_hex}" in _analyze(hex_value).flag_candidates


def test_urlsafe_base64_with_missing_padding_is_distinct_from_standard():
    plain = "FLAG{ÿÿ}"
    encoded = base64.urlsafe_b64encode(plain.encode()).decode().rstrip("=")
    assert "_" in encoded or "-" in encoded
    decoded = UniversalEncodingSolver().decode(encoded)
    assert ("urlsafe_base64", plain) in decoded
    assert all(method != "base64" for method, _output in decoded)


def test_recursive_base64_hex_base32_path_finds_flag_at_depth_three():
    base32 = base64.b32encode(b"FLAG{three_layers}").decode()
    hex_value = base32.encode().hex()
    encoded = base64.b64encode(hex_value.encode()).decode()
    result = _analyze(encoded)
    assert result is not None
    assert result.flag_candidates == ("FLAG{three_layers}",)
    step = next(item for item in result.steps if item.flag_candidate)
    assert step.depth == 3
    assert step.transformation_path == ("base64", "hex_ascii", "base32")


def test_question_text_and_strings_sources_preserve_input_order_and_deduplicate():
    question = base64.b32encode(b"FLAG{question}").decode()
    text = b"FLAG{text}".hex()
    string = " ".join(str(byte) for byte in b"FLAG{strings}")
    challenge = ChallengeInput(
        question,
        [_file("sample.txt", text_content=text, strings=[string, string])],
    )
    result = UniversalEncodingAnalyzer().analyze(challenge)
    assert result is not None
    assert result.flag_candidates == (
        "FLAG{question}",
        "FLAG{text}",
        "FLAG{strings}",
    )
    assert [step.source for step in result.steps if step.flag_candidate] == [
        "question",
        "sample.txt:text_content",
        "sample.txt:strings[0]",
    ]


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not@base32",
        "~~~~~",
        "<~broken",
        "abc",
        "0101010",
        "777 400",
        "70, 999",
        "123",
        "////",
    ],
)
def test_invalid_ambiguous_and_non_utf8_inputs_are_ignored(value: str):
    assert _analyze(value) is None


def test_depth_source_step_and_long_input_limits_are_bounded():
    value = "FLAG{too_deep}"
    for _ in range(MAX_UNIVERSAL_ENCODING_DEPTH + 1):
        value = base64.b32encode(value.encode()).decode()
    deep = _analyze(value)
    assert deep is not None
    assert "FLAG{too_deep}" not in deep.flag_candidates
    assert max(step.depth for step in deep.steps) == MAX_UNIVERSAL_ENCODING_DEPTH

    many = ChallengeInput(
        "plain question",
        [_file("many.txt", strings=[b"FLAG{x}".hex()] * (MAX_UNIVERSAL_ENCODING_SOURCES + 20))],
    )
    bounded = UniversalEncodingAnalyzer().analyze(many)
    assert bounded is not None
    assert len(bounded.steps) <= MAX_UNIVERSAL_ENCODING_STEPS

    long_result = _analyze("A" * (MAX_UNIVERSAL_ENCODING_INPUT + 1))
    assert long_result is None


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit()])
def test_process_control_exceptions_are_not_swallowed(monkeypatch, error):
    analyzer = UniversalEncodingAnalyzer()
    monkeypatch.setattr(
        analyzer._solver,
        "decode",
        lambda _value: (_ for _ in ()).throw(error),
    )
    with pytest.raises(type(error)):
        analyzer.analyze(ChallengeInput("MZXW6YTBOI======"))


def test_inputs_and_existing_dto_are_not_mutated():
    strings = [b"FLAG{stable}".hex()]
    file_result = _file("stable.txt", text_content="unchanged", strings=strings)
    challenge = ChallengeInput("unchanged question", [file_result])
    before = (challenge.question, file_result.text_content, tuple(file_result.strings))
    UniversalEncodingAnalyzer().analyze(challenge)
    assert before == (challenge.question, file_result.text_content, tuple(file_result.strings))


def test_challenge_service_fast_path_avoids_controller_and_ai(tmp_path: Path):
    path = tmp_path / "encoded.txt"
    path.write_text(base64.b32encode(b"FLAG{local_fast_path}").decode(), encoding="utf-8")
    controller = MagicMock()
    category_analyzer = MagicMock()
    category_analyzer.analyze.return_value = "Crypto"
    service = ChallengeService(controller=controller, analyzer=category_analyzer)

    execution = service.solve_with_usage("decode attachment", [path])

    assert execution.result.flag == "FLAG{local_fast_path}"
    assert execution.result.confidence == 90
    assert "base32" in (execution.result.reason or "")
    assert "再帰深度=1" in (execution.result.reason or "")
    assert execution.ai_usage.local_solution_avoided_ai is True
    controller.process_challenge.assert_not_called()
    controller.process_challenge_with_usage.assert_not_called()


def test_plain_flag_example_in_question_is_not_fast_solved():
    controller = MagicMock()
    expected = MagicMock()
    controller.process_challenge.return_value = expected
    service = ChallengeService(controller=controller, analyzer=MagicMock())

    assert service.solve("Flag format example: FLAG{example}") is expected
    controller.process_challenge.assert_called_once()


def test_modules_do_not_add_execution_network_or_ai_dependencies():
    sources = "".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "app/solver/universal_encoding_solver.py",
            "app/solver/universal_encoding_analyzer.py",
        )
    )
    for forbidden in (
        "subprocess",
        "socket",
        "urllib",
        "requests",
        "OpenAI",
        "exec(",
        "eval(",
        "\ncompile(",
    ):
        assert forbidden not in sources
