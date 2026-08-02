import base64
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.analyzer.analyzer import Analyzer
from app.challenge.challenge_context_builder import ChallengeContextBuilder
from app.challenge.challenge_input import ChallengeInput
from app.challenge.challenge_service import ChallengeService
from app.file.file_input import FileInput
from app.file.file_loader import FileLoader
from app.file.static_file_analyzer import StaticFileAnalyzer
from app.solver.caesar_analyzer import CaesarAnalyzer
from app.solver.caesar_result import CaesarCandidate, CaesarResult
from app.solver.caesar_solver import MAX_INPUT_LENGTH, CaesarSolver
from app.solver.xor_result import SingleByteXorResult, XorCandidate


def _encode(plaintext: str, shift: int) -> str:
    encoded: list[str] = []
    for character in plaintext:
        if "A" <= character <= "Z":
            encoded.append(
                chr((ord(character) - ord("A") + shift) % 26 + ord("A"))
            )
        elif "a" <= character <= "z":
            encoded.append(
                chr((ord(character) - ord("a") + shift) % 26 + ord("a"))
            )
        else:
            encoded.append(character)
    return "".join(encoded)


def _solve(plaintext: str, shift: int) -> CaesarResult:
    return CaesarSolver().solve(_encode(plaintext, shift), "test")


def _candidate(result: CaesarResult, plaintext: str) -> CaesarCandidate:
    return next(
        candidate
        for candidate in result.candidates
        if candidate.plaintext == plaintext
    )


def _make_input(name: str, content: bytes) -> FileInput:
    path = Path(name)
    return FileInput(
        name=name,
        path=path,
        size=len(content),
        extension=path.suffix,
        content=content,
    )


def test_decodes_caesar_shifted_english():
    candidate = _candidate(_solve("Hello world", 3), "Hello world")

    assert candidate.shift == 3


def test_decodes_rot13():
    candidate = _candidate(_solve("FLAG{rot13_test}", 13), "FLAG{rot13_test}")

    assert candidate.shift == 13


def test_preserves_uppercase_lowercase_symbols_numbers_and_japanese():
    plaintext = "FLAG{Mixed_case_123} 日本語\nnext"
    candidate = _candidate(_solve(plaintext, 7), plaintext)

    assert candidate.plaintext == plaintext


@pytest.mark.parametrize("shift", range(1, 26))
def test_tries_every_nonzero_shift(shift):
    plaintext = "FLAG{all_shifts}"

    assert _candidate(_solve(plaintext, shift), plaintext).shift == shift


def test_shift_zero_is_not_returned():
    result = CaesarSolver().solve("ordinary text", "test")

    assert all(candidate.shift != 0 for candidate in result.candidates)


@pytest.mark.parametrize("flag", ["FLAG{upper}", "flag{lower}", "CTF{ctf}"])
def test_flags_are_ranked_first(flag):
    result = _solve(flag, 11)

    assert result.candidates[0].plaintext == flag
    assert result.candidates[0].contains_flag is True


def test_candidate_count_score_range_and_order():
    result = _solve("Enter password for this challenge", 5)

    assert len(result.candidates) <= 5
    assert all(0.0 <= candidate.score <= 1.0 for candidate in result.candidates)
    assert list(result.candidates) == sorted(
        result.candidates,
        key=lambda candidate: (
            not candidate.contains_flag,
            -candidate.score,
            candidate.shift,
        ),
    )


def test_equal_scores_use_shift_order():
    result = CaesarSolver().solve("BBBBBBBB", "test")
    grouped: dict[float, list[int]] = {}
    for candidate in result.candidates:
        grouped.setdefault(candidate.score, []).append(candidate.shift)

    assert all(shifts == sorted(shifts) for shifts in grouped.values())


def test_plaintext_candidates_are_unique():
    result = _solve("Enter password", 13)
    plaintexts = [candidate.plaintext for candidate in result.candidates]

    assert len(plaintexts) == len(set(plaintexts))


@pytest.mark.parametrize("value", ["", "abc", "123456", "!@#$%^", "12ab34"])
def test_invalid_or_insufficient_inputs_are_ignored(value):
    result = CaesarAnalyzer().analyze(value, [value])

    assert result.candidates == ()


def test_oversized_input_is_ignored_before_solver_call():
    solver = MagicMock()
    analyzer = CaesarAnalyzer(solver=solver)
    oversized = "A" * (MAX_INPUT_LENGTH + 1)

    result = analyzer.analyze(oversized, [oversized])

    assert result.candidates == ()
    solver.solve.assert_not_called()


def test_plain_english_does_not_create_high_scoring_noise():
    result = CaesarAnalyzer().analyze(
        "This is ordinary English text.",
        ["This is ordinary English text."],
    )

    assert all(candidate.score < 0.9 for candidate in result.candidates)


def test_analyzer_does_not_modify_strings():
    strings = [_encode("FLAG{preserved}", 3)]
    original = strings.copy()

    CaesarAnalyzer().analyze(None, strings)

    assert strings == original


def test_static_analyzer_uses_base64_decoded_caesar_string():
    caesar_text = _encode("FLAG{base64_caesar}", 13)
    encoded = base64.b64encode(caesar_text.encode())
    result = StaticFileAnalyzer().analyze(_make_input("cipher.txt", encoded))

    assert caesar_text in result.strings
    assert result.caesar_result is not None
    assert _candidate(result.caesar_result, "FLAG{base64_caesar}").shift == 13


def test_file_result_holds_structured_caesar_result():
    ciphertext = _encode("FLAG{structured}", 4).encode()
    result = StaticFileAnalyzer().analyze(_make_input("cipher.txt", ciphertext))

    assert isinstance(result.caesar_result, CaesarResult)
    assert _candidate(result.caesar_result, "FLAG{structured}").shift == 4
    assert "FLAG{structured}" not in result.strings


def _make_service() -> tuple[ChallengeService, MagicMock]:
    analyzer = MagicMock(spec=Analyzer)
    analyzer.analyze.return_value = "Crypto"
    controller = MagicMock()
    return (
        ChallengeService(
            controller=controller,
            analyzer=analyzer,
            file_loader=FileLoader(),
            file_analyzer=StaticFileAnalyzer(),
        ),
        controller,
    )


def test_caesar_flag_uses_fast_path_without_ai(tmp_path: Path):
    cipher = tmp_path / "cipher.txt"
    cipher.write_text(_encode("FLAG{fast_caesar}", 7), encoding="utf-8")
    service, controller = _make_service()

    result = service.solve("Analyze", [cipher])

    assert result.flag == "FLAG{fast_caesar}"
    assert result.confidence == 90
    assert result.hypothesis is None
    assert result.next_actions == []
    assert result.gemini_prompt is None
    assert "シフト：7" in result.reason
    assert "cipher.txt" in result.reason
    controller.process_challenge.assert_not_called()
    controller.ai_client.generate.assert_not_called()


def test_rot13_reason_is_explicit(tmp_path: Path):
    cipher = tmp_path / "rot13.txt"
    cipher.write_text("SYNT{ebg13_ernfba}", encoding="utf-8")
    service, _ = _make_service()

    result = service.solve("Analyze", [cipher])

    assert "シフト：13（ROT13）" in result.reason


def test_non_flag_candidate_delegates_to_controller(tmp_path: Path):
    cipher = tmp_path / "cipher.txt"
    cipher.write_text(_encode("Enter password", 9), encoding="utf-8")
    service, controller = _make_service()
    expected = object()
    controller.process_challenge.return_value = expected

    result = service.solve("Analyze", [cipher])

    assert result is expected
    controller.process_challenge.assert_called_once()


def test_non_flag_candidate_is_shown_in_context():
    ciphertext = _encode("Enter password", 9).encode()
    file_result = StaticFileAnalyzer().analyze(
        _make_input("cipher.txt", ciphertext)
    )
    context = ChallengeContextBuilder().build(
        ChallengeInput(question="Analyze", files=[file_result])
    )

    assert "Caesar / ROT候補：" in context
    assert "shift=9" in context
    assert "Enter password" in context
    assert "検出元：テキスト内容" in context


def test_context_omits_caesar_section_without_candidates():
    file_result = StaticFileAnalyzer().analyze(
        _make_input("plain.txt", b"1234567890")
    )
    context = ChallengeContextBuilder().build(
        ChallengeInput(question="Analyze", files=[file_result])
    )

    assert "Caesar / ROT候補：" not in context


def test_xor_candidates_are_not_reintroduced_to_caesar():
    caesar_flag = _encode("FLAG{do_not_chain}", 13)
    analyzer = StaticFileAnalyzer()
    analyzer._xor_analyzer = MagicMock()
    analyzer._xor_analyzer.analyze.return_value = SingleByteXorResult(
        candidates=(
            XorCandidate(
                key=0x23,
                plaintext=caesar_flag,
                score=0.8,
                contains_flag=False,
                source="バイナリデータ",
            ),
        )
    )
    analyzer._caesar_analyzer = MagicMock()
    analyzer._caesar_analyzer.analyze.return_value = CaesarResult(candidates=())

    analyzer.analyze(_make_input("combined.bin", b"ordinary_data"))

    call = analyzer._caesar_analyzer.analyze.call_args
    assert caesar_flag not in call.kwargs["strings"]
    assert set(call.kwargs) == {"text_content", "strings"}
