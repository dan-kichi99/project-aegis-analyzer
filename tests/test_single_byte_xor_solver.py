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
from app.solver.single_byte_xor_analyzer import SingleByteXorAnalyzer
from app.solver.single_byte_xor_solver import (
    MAX_CANDIDATES,
    MAX_INPUT_BYTES,
    SingleByteXorSolver,
)
from app.solver.xor_result import SingleByteXorResult, XorCandidate


def _xor(plaintext: str, key: int) -> bytes:
    return bytes(byte ^ key for byte in plaintext.encode())


def _solve(plaintext: str, key: int = 0x23) -> SingleByteXorResult:
    return SingleByteXorSolver().solve(_xor(plaintext, key), "test")


def _candidate(result: SingleByteXorResult, plaintext: str) -> XorCandidate:
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


def test_decodes_ascii_with_known_single_byte_key():
    candidate = _candidate(_solve("Enter password:"), "Enter password:")

    assert candidate.key == 0x23
    assert candidate.source == "test"


@pytest.mark.parametrize(
    ("flag", "key"),
    [
        ("FLAG{upper}", 0x01),
        ("flag{lower}", 0x23),
        ("CTF{ctf}", 0xFF),
    ],
)
def test_flag_candidate_is_ranked_first(flag, key):
    result = _solve(flag, key)

    assert result.candidates[0].plaintext == flag
    assert result.candidates[0].contains_flag is True
    assert result.candidates[0].key == key


def test_key_zero_is_explored_but_original_is_not_returned():
    result = SingleByteXorSolver().solve(b"ordinary text", "test")

    assert all(candidate.key != 0 for candidate in result.candidates)


def test_candidate_count_score_range_and_order():
    result = _solve("Enter password and correct key")

    assert len(result.candidates) <= MAX_CANDIDATES
    assert all(0.0 <= candidate.score <= 1.0 for candidate in result.candidates)
    assert list(result.candidates) == sorted(
        result.candidates,
        key=lambda candidate: (
            not candidate.contains_flag,
            -candidate.score,
            candidate.key,
        ),
    )


def test_tied_candidates_are_sorted_by_key():
    result = SingleByteXorSolver().solve(b"AAAA", "test")
    score_groups: dict[float, list[int]] = {}
    for candidate in result.candidates:
        score_groups.setdefault(candidate.score, []).append(candidate.key)

    assert all(keys == sorted(keys) for keys in score_groups.values())


def test_plaintexts_are_not_duplicated():
    result = _solve("Enter password:")
    plaintexts = [candidate.plaintext for candidate in result.candidates]

    assert len(plaintexts) == len(set(plaintexts))


def test_non_utf8_and_control_heavy_candidates_are_handled_safely():
    result = SingleByteXorSolver().solve(bytes(range(256)), "test")

    assert result.candidates == ()


@pytest.mark.parametrize("data", [b"", b"a", b"abc"])
def test_too_short_input_is_ignored(data):
    assert SingleByteXorSolver().solve(data, "test").candidates == ()


def test_oversized_input_is_ignored():
    data = b"A" * (MAX_INPUT_BYTES + 1)

    assert SingleByteXorSolver().solve(data, "test").candidates == ()


def test_oversized_hex_is_rejected_before_solving():
    solver = MagicMock()
    analyzer = SingleByteXorAnalyzer(solver=solver)
    oversized = "41" * (MAX_INPUT_BYTES + 1)

    result = analyzer.analyze(
        content=oversized.encode(),
        detected_type="text",
        extension=".txt",
        text_content=oversized,
        strings=[oversized],
    )

    assert result.candidates == ()
    solver.solve.assert_not_called()


def test_invalid_hex_is_ignored():
    result = SingleByteXorAnalyzer().analyze(
        content=b"not hex",
        detected_type="text",
        extension=".txt",
        text_content="12ZZ34GG",
        strings=["123", "ABC"],
    )

    assert result.candidates == ()


def test_spaced_hex_is_decoded():
    encrypted = _xor("FLAG{spaced_hex}", 0x23)
    spaced = " ".join(f"{byte:02x}" for byte in encrypted)
    result = SingleByteXorAnalyzer().analyze(
        content=spaced.encode(),
        detected_type="text",
        extension=".txt",
        text_content=spaced,
        strings=[spaced],
    )

    assert _candidate(result, "FLAG{spaced_hex}").key == 0x23


def test_normal_plaintext_is_not_given_a_flag_priority():
    result = SingleByteXorSolver().solve(b"This is ordinary text.", "test")

    assert all(not candidate.contains_flag for candidate in result.candidates)
    assert all(candidate.score < 1.0 for candidate in result.candidates)


def test_static_analyzer_stores_structured_xor_result_without_changing_strings():
    encrypted = _xor("FLAG{structured}", 0x23)
    result = StaticFileAnalyzer().analyze(_make_input("cipher.bin", encrypted))

    assert result.xor_result is not None
    assert _candidate(result.xor_result, "FLAG{structured}").key == 0x23
    assert "FLAG{structured}" not in result.strings


def test_duplicate_hex_inputs_are_analyzed_once():
    encrypted = _xor("FLAG{deduplicated}", 0x42).hex()
    result = SingleByteXorAnalyzer().analyze(
        content=encrypted.encode(),
        detected_type="text",
        extension=".txt",
        text_content=encrypted,
        strings=[encrypted, encrypted.upper()],
    )

    matches = [
        candidate
        for candidate in result.candidates
        if candidate.plaintext == "FLAG{deduplicated}"
    ]
    assert len(matches) == 1


def _make_service() -> tuple[ChallengeService, MagicMock]:
    analyzer = MagicMock(spec=Analyzer)
    analyzer.analyze.return_value = "Misc"
    controller = MagicMock()
    service = ChallengeService(
        controller=controller,
        analyzer=analyzer,
        file_loader=FileLoader(),
        file_analyzer=StaticFileAnalyzer(),
    )
    return service, controller


def test_xor_flag_uses_fast_path_without_ai(tmp_path: Path):
    cipher = tmp_path / "cipher.bin"
    cipher.write_bytes(_xor("FLAG{xor_fast_path}", 0x23))
    service, controller = _make_service()

    result = service.solve("Analyze", [cipher])

    assert result.flag == "FLAG{xor_fast_path}"
    assert result.confidence == 90
    assert "鍵：0x23" in result.reason
    assert "cipher.bin" in result.reason
    controller.process_challenge.assert_not_called()
    controller.ai_client.generate.assert_not_called()


def test_hex_xor_flag_uses_existing_fast_path(tmp_path: Path):
    cipher = tmp_path / "cipher.txt"
    encrypted = _xor("CTF{hex_xor_fast_path}", 0x42)
    cipher.write_text(
        " ".join(f"{byte:02x}" for byte in encrypted),
        encoding="ascii",
    )
    service, controller = _make_service()

    result = service.solve("Analyze", [cipher])

    assert result.flag == "CTF{hex_xor_fast_path}"
    assert "鍵：0x42" in result.reason
    assert "検出元：テキスト内容" in result.reason
    controller.process_challenge.assert_not_called()


def test_non_flag_candidate_delegates_to_controller(tmp_path: Path):
    cipher = tmp_path / "cipher.bin"
    cipher.write_bytes(_xor("Enter password:", 0x23))
    service, controller = _make_service()
    expected = object()
    controller.process_challenge.return_value = expected

    result = service.solve("Analyze", [cipher])

    assert result is expected
    controller.process_challenge.assert_called_once()


def test_non_flag_candidate_is_in_ai_context():
    file_result = StaticFileAnalyzer().analyze(
        _make_input("cipher.bin", _xor("Enter password:", 0x23))
    )
    context = ChallengeContextBuilder().build(
        ChallengeInput(question="Analyze", files=[file_result])
    )

    assert "単一バイトXOR候補：" in context
    assert "key=0x23" in context
    assert "Enter password:" in context
    assert "検出元：バイナリデータ" in context


def test_context_omits_xor_section_without_candidates():
    file_result = StaticFileAnalyzer().analyze(
        _make_input("plain.txt", b"ordinary text")
    )
    context = ChallengeContextBuilder().build(
        ChallengeInput(question="Analyze", files=[file_result])
    )

    assert "単一バイトXOR候補：" not in context


def test_original_strings_list_is_not_modified_by_xor_analyzer():
    strings = [_xor("FLAG{original}", 0x23).hex()]
    original = strings.copy()

    SingleByteXorAnalyzer().analyze(
        content=b"",
        detected_type="text",
        extension=".txt",
        text_content=None,
        strings=strings,
    )

    assert strings == original
