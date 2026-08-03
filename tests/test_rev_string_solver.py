import base64
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.challenge.challenge_input import ChallengeInput
from app.challenge.challenge_service import ChallengeService
from app.file.file_analysis_result import FileAnalysisResult
from app.file.file_input import FileInput
from app.file.static_file_analyzer import StaticFileAnalyzer
from app.solver.rev_string_analyzer import RevStringAnalyzer
from app.solver.rev_string_result import MAX_REV_STRING_CANDIDATES
from app.solver.rev_string_solver import (
    MAX_REV_STRING_INPUT,
    MAX_REV_STRING_SOURCES,
    RevStringSolver,
)


def _solve(value: str):
    return RevStringSolver().solve([("input", value)])


def _file(name: str, text: str | None = None, strings=None):
    return FileAnalysisResult(name, len(text or ""), Path(name).suffix, "unknown", text, strings or [])


@pytest.mark.parametrize(
    ("value", "flag", "method"),
    [
        ('"pico" + "CTF" + "{concat}"', "picoCTF{concat}", "string_concat"),
        ('builder.append("FLAG{"); builder.append("append}");', "FLAG{append}", "string_builder"),
        ("char x[] = {'C','T','F','{','c','h','a','r','}'};", "CTF{char}", "char_array"),
        ("ASCII [70,76,65,71,123,105,110,116,125]", "FLAG{int}", "ascii_integers"),
        ("bytes([70,76,65,71,123,98,121,116,101,115,125])", "FLAG{bytes}", "ascii_integers"),
        ("bytearray([67,84,70,123,98,97,125])", "CTF{ba}", "ascii_integers"),
        ("464c41477b6865787d", "FLAG{hex}", "hex_ascii"),
        ('"}esrever{FTCocip"[::-1]', "picoCTF{reverse}", "reverse"),
        ('value = "}esrever{GALF"; value.reverse();', "FLAG{reverse}", "reverse"),
    ],
)
def test_reconstruction_patterns(value: str, flag: str, method: str):
    result = _solve(value)
    assert result is not None
    assert result.candidates[0].flag_candidate == flag
    assert result.candidates[0].method == method


@pytest.mark.parametrize(
    ("encoded", "flag", "method"),
    [
        (base64.b64encode(b"FLAG{b64}").decode(), "FLAG{b64}", "base64"),
        (base64.urlsafe_b64encode("FLAG{ÿÿ}".encode()).decode(), "FLAG{ÿÿ}", "urlsafe_base64"),
        (base64.b32encode(b"FLAG{b32}").decode(), "FLAG{b32}", "base32"),
        (base64.b85encode(b"FLAG{b85}").decode(), "FLAG{b85}", "base85"),
        (base64.a85encode(b"FLAG{a85}").decode(), "FLAG{a85}", "ascii85"),
    ],
)
def test_base_encodings_reuse_universal_solver(encoded: str, flag: str, method: str):
    result = _solve(encoded)
    assert result is not None
    assert result.candidates[0].flag_candidate == flag
    assert result.candidates[0].method == method


def test_adjacent_split_strings_reconstruct_in_order():
    values = [("s0", "pico"), ("s1", "CTF"), ("s2", "{split}")]
    result = RevStringSolver().solve(values)
    assert result is not None
    candidate = result.candidates[0]
    assert candidate.flag_candidate == "picoCTF{split}"
    assert candidate.used_strings == 3
    assert candidate.reconstruction_path == ("fragments", "concatenate")
    assert candidate.source == "s0"


def test_quoted_lines_reconstruct_as_fragments():
    result = RevStringSolver().solve(
        [("a", '"HTB"'), ("b", '"{quoted}"')]
    )
    assert result is not None
    assert result.candidates[0].flag_candidate == "HTB{quoted}"


def test_unknown_prefix_is_supported_without_site_allowlist():
    result = RevStringSolver().solve(
        [("a", "custom_ctf"), ("b", "{unknown}")]
    )
    assert result is not None
    assert result.candidates[0].flag_candidate == "custom_ctf{unknown}"


def test_single_byte_xor_reconstruction():
    flag = b"FLAG{xor}"
    encrypted = [item ^ 23 for item in flag]
    result = _solve(f"bytes({encrypted}); key = 23; x ^ 23")
    assert result is not None
    assert any(
        item.flag_candidate == "FLAG{xor}" and item.method == "single_byte_xor"
        for item in result.candidates
    )


def test_utf16le_strings_from_task128_are_reused():
    content = b"MZ\x00" + "DUCTF{wide}".encode("utf-16-le") + b"\x00"
    file_result = StaticFileAnalyzer().analyze(
        FileInput("wide.exe", Path("wide.exe"), len(content), ".exe", content)
    )
    assert "DUCTF{wide}" in file_result.strings
    result = RevStringAnalyzer().analyze(ChallengeInput("solve", [file_result]))
    assert result is not None
    assert result.candidates[0].flag_candidate == "DUCTF{wide}"


def test_question_text_and_strings_inputs_preserve_order_and_deduplicate():
    challenge = ChallengeInput(
        "FLAG{question}",
        [_file("sample.bin", "CTF{text}", ["HTB{strings}", "HTB{strings}"])],
    )
    result = RevStringAnalyzer().analyze(challenge)
    assert result is not None
    assert [item.flag_candidate for item in result.candidates] == [
        "FLAG{question}", "CTF{text}", "HTB{strings}",
    ]


@pytest.mark.parametrize(
    "value",
    [
        "", "ordinary", "FLAG{", "{body}", "ab{short}",
        "bad prefix{value}", "FLAG{has space}", "FLAG{unterminated",
        "[256, 1, 2]", "bytes([255,254,253])", "0xGG", "[::-2]",
        "reverse()", "x ^ dynamic_key", "one two three", "{}",
    ],
)
def test_invalid_partial_ambiguous_and_out_of_range_values_are_ignored(value: str):
    assert _solve(value) is None


def test_non_adjacent_and_too_many_fragments_do_not_reconstruct():
    assert RevStringSolver().solve(
        [("a", "FLAG"), ("gap", "has whitespace gap"), ("b", "{no}")]
    ) is None
    values = [(str(index), part) for index, part in enumerate(
        ["p", "i", "c", "o", "C", "T", "F", "{", "too_many}"]
    )]
    result = RevStringSolver().solve(values)
    assert result is None or all(
        item.flag_candidate != "picoCTF{too_many}" for item in result.candidates
    )


def test_source_candidate_and_input_limits_are_bounded():
    many = [(str(index), f"FLAG{{item_{index}}}") for index in range(150)]
    result = RevStringSolver().solve(many)
    assert result is not None
    assert len(result.candidates) == MAX_REV_STRING_CANDIDATES
    assert result.truncated is True
    assert MAX_REV_STRING_SOURCES == 100
    assert _solve("A" * (MAX_REV_STRING_INPUT + 1)) is None


def test_challenge_service_fast_path_avoids_controller_and_ai(tmp_path: Path):
    path = tmp_path / "fragments.bin"
    path.write_bytes(b"picoCTF\x00{local_rev}\x00")
    controller = MagicMock()
    category = MagicMock()
    category.analyze.return_value = "Rev"
    execution = ChallengeService(controller, category).solve_with_usage("solve", [path])
    assert execution.result.flag == "picoCTF{local_rev}"
    assert execution.result.confidence == 90
    assert "string_fragments" in (execution.result.reason or "")
    assert "使用Strings数=2" in (execution.result.reason or "")
    assert execution.ai_usage.local_solution_avoided_ai is True
    controller.process_challenge.assert_not_called()
    controller.process_challenge_with_usage.assert_not_called()


def test_input_dto_is_unchanged_and_no_forbidden_dependencies_exist():
    strings = ["pico", "CTF", "{stable}"]
    challenge = ChallengeInput("solve", [_file("stable.bin", strings=strings)])
    before = tuple(challenge.files[0].strings)
    assert RevStringAnalyzer().analyze(challenge) is not None
    assert tuple(challenge.files[0].strings) == before
    source = Path("app/solver/rev_string_solver.py").read_text(encoding="utf-8")
    for forbidden in (
        "subprocess", "Ghidra", "radare2", "objdump", "OpenAI",
        "requests", "socket.", "\nexec(", "\neval(", "\ncompile(",
    ):
        assert forbidden not in source
