from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.analyzer.analyzer import Analyzer
from app.challenge.challenge_context_builder import ChallengeContextBuilder
from app.challenge.challenge_input import ChallengeInput
from app.challenge.challenge_service import ChallengeService
from app.file.file_analysis_result import FileAnalysisResult
from app.solver.rsa_analyzer import RsaAnalyzer
from app.solver.rsa_parameter_extractor import (
    MAX_PARAMETER_CHARACTERS,
    RsaParameterExtractor,
)
from app.solver.rsa_result import RsaParameters
from app.solver.rsa_solver import MAX_MODULUS_BITS, RsaSolver


def _parameters(**values) -> RsaParameters:
    return RsaParameters(source="test", **values)


def _file(name: str, text: str) -> FileAnalysisResult:
    return FileAnalysisResult(
        name=name,
        size=len(text),
        extension=Path(name).suffix,
        detected_type="text",
        text_content=text,
        strings=[text],
    )


def _flag_parameters(flag: str) -> RsaParameters:
    message = int.from_bytes(flag.encode(), "big")
    return _parameters(n=message + 1_000_003, c=message, d=1)


def test_extracts_decimal_parameters():
    result = RsaParameterExtractor().extract(
        "n = 3233\ne = 17\nc = 2790",
        "test",
    )

    assert result == _parameters(n=3233, e=17, c=2790)


def test_extracts_colon_separator_and_flexible_spaces():
    result = RsaParameterExtractor().extract(
        "n:3233 e : 17 c: 2790 p =61 q= 53",
        "test",
    )

    assert result == _parameters(n=3233, e=17, c=2790, p=61, q=53)


def test_extracts_hexadecimal_values():
    result = RsaParameterExtractor().extract("n=0xCA1 e=0x11 c=0xAE6", "test")

    assert result is not None
    assert (result.n, result.e, result.c) == (3233, 17, 2790)


@pytest.mark.parametrize("text", ["nonce=3233", "filename=17", "score=42"])
def test_does_not_extract_parameter_names_inside_identifiers(text):
    assert RsaParameterExtractor().extract(text, "test") is None


def test_given_p_and_q_compute_private_values_and_decrypt():
    result = RsaSolver().solve(
        _parameters(n=3233, e=17, c=2790, p=61, q=53)
    )

    assert result.plaintext == "A"
    assert result.parameters.phi == 3120
    assert result.parameters.d == 2753
    assert result.attempts[0].method == "与えられたp・qを使用"


def test_mismatched_factors_fail_safely():
    result = RsaSolver().solve(
        _parameters(n=3233, e=17, c=2790, p=59, q=53)
    )

    assert result.plaintext is None
    assert "一致しません" in result.attempts[0].detail


def test_noninvertible_exponent_fails_safely():
    result = RsaSolver().solve(
        _parameters(n=3233, e=12, c=2790, p=61, q=53)
    )

    assert result.plaintext is None
    assert "gcd(e, phi) != 1" in result.attempts[0].detail


def test_given_d_decrypts():
    result = RsaSolver().solve(_parameters(n=3233, e=17, c=2790, d=2753))

    assert result.plaintext == "A"
    assert result.attempts[0].method == "与えられたdを使用"


def test_small_modulus_is_factored_by_trial_division():
    result = RsaSolver().solve(_parameters(n=3233, e=17, c=2790))

    assert result.plaintext == "A"
    assert {result.parameters.p, result.parameters.q} == {53, 61}
    assert result.attempts[0].method == "小さいnの試し割り"


def test_prime_modulus_fails_safely():
    result = RsaSolver().solve(_parameters(n=101, e=3, c=10))

    assert result.plaintext is None
    assert result.attempts[0].success is False
    assert "因数を特定できません" in result.attempts[0].detail


def test_fermat_factors_nearby_large_factors():
    p, q = 1_000_003, 1_000_033
    n = p * q
    plaintext_integer = 65
    e = 65_537
    c = pow(plaintext_integer, e, n)

    result = RsaSolver().solve(_parameters(n=n, e=e, c=c))

    assert result.plaintext == "A"
    assert {result.parameters.p, result.parameters.q} == {p, q}
    assert result.attempts[0].method == "Fermat因数分解"


def test_fermat_stops_at_configured_limit(monkeypatch):
    monkeypatch.setattr("app.solver.rsa_solver.MAX_FERMAT_ATTEMPTS", 3)
    result = RsaSolver().solve(
        _parameters(n=1_000_003 * 3_000_017, e=65_537, c=65)
    )

    assert result.plaintext is None
    assert "3回" in result.attempts[0].detail
    assert "上限で停止" in result.attempts[0].detail


def test_modulus_over_bit_limit_is_rejected():
    result = RsaSolver().solve(
        _parameters(n=1 << (MAX_MODULUS_BITS + 1), e=3, c=1)
    )

    assert result.plaintext is None
    assert "許容範囲外" in result.attempts[0].detail


def test_oversized_parameter_text_is_rejected():
    text = "n=" + "9" * (MAX_PARAMETER_CHARACTERS + 1)

    assert RsaParameterExtractor().extract(text, "test") is None


def test_plaintext_integer_uses_big_endian_bytes():
    message = int.from_bytes(b"AB", "big")
    result = RsaSolver().solve(_parameters(n=message + 1, c=message, d=1))

    assert result.plaintext == "AB"


def test_non_utf8_plaintext_is_not_accepted_as_flag():
    result = RsaSolver().solve(_parameters(n=300, c=255, d=1))

    assert result.plaintext is None
    assert result.contains_flag is False
    assert "UTF-8ではありません" in result.attempts[0].detail


def test_failed_reencryption_is_not_accepted():
    result = RsaSolver().solve(_parameters(n=3233, e=17, c=2790, d=2))

    assert result.plaintext is None
    assert "再暗号化検証に失敗" in result.attempts[0].detail


@pytest.mark.parametrize("flag", ["FLAG{rsa}", "flag{rsa}", "CTF{rsa}"])
def test_detects_supported_flag_formats(flag):
    result = RsaSolver().solve(_flag_parameters(flag))

    assert result.plaintext == flag
    assert result.contains_flag is True


def _service() -> tuple[ChallengeService, MagicMock]:
    analyzer = MagicMock(spec=Analyzer)
    analyzer.analyze.return_value = "Crypto"
    controller = MagicMock()
    return ChallengeService(controller, analyzer), controller


def test_rsa_flag_uses_fast_path_without_ai():
    flag = "FLAG{rsa_fast_path}"
    parameters = _flag_parameters(flag)
    question = f"n={parameters.n} c={parameters.c} d=1"
    service, controller = _service()

    result = service.solve(question)

    assert result.flag == flag
    assert result.confidence == 90
    assert result.hypothesis is None
    assert result.next_actions == []
    assert result.gemini_prompt is None
    assert "方式：与えられたdを使用" in result.reason
    assert "問題文" in result.reason
    controller.process_challenge.assert_not_called()
    controller.ai_client.generate.assert_not_called()


def test_flagless_diagnostic_delegates_to_controller():
    service, controller = _service()
    expected = object()
    controller.process_challenge.return_value = expected

    result = service.solve("n=3233 e=17 c=2790")

    assert result is expected
    challenge = controller.process_challenge.call_args.args[0]
    assert challenge.rsa_result is not None
    assert challenge.rsa_result.plaintext == "A"


def test_rsa_diagnostic_is_in_context_for_question_only():
    challenge = ChallengeInput(question="n=3233 e=17 c=2790")
    challenge.rsa_result = RsaAnalyzer().analyze(challenge)

    context = ChallengeContextBuilder().build(challenge)

    assert "RSA診断：" in context
    assert "検出元：問題文" in context
    assert "方式：小さいnの試し割り" in context
    assert "復号結果：'A'" in context
    assert "Flag：未検出" in context


def test_context_omits_rsa_section_without_parameters():
    context = ChallengeContextBuilder().build(
        ChallengeInput(question="ordinary challenge")
    )

    assert "RSA診断：" not in context


def test_parameters_from_different_files_are_not_combined():
    challenge = ChallengeInput(
        question="RSA challenge",
        files=[
            _file("n.txt", "n=3233"),
            _file("rest.txt", "e=17 c=2790"),
        ],
    )

    result = RsaAnalyzer().analyze(challenge)

    assert result is not None
    assert result.plaintext is None
    assert result.parameters.source == "ファイル「n.txt」のテキスト内容"


def test_question_flag_example_is_not_treated_as_answer():
    service, controller = _service()
    expected = object()
    controller.process_challenge.return_value = expected

    result = service.solve("RSA Flag format: FLAG{example}")

    assert result is expected
    controller.process_challenge.assert_called_once()
