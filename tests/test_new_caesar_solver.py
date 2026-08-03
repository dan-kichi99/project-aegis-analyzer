from pathlib import Path
from unittest.mock import MagicMock

from app.challenge.challenge_input import ChallengeInput
from app.challenge.challenge_service import ChallengeService
from app.file.file_analysis_result import FileAnalysisResult
from app.solver.new_caesar_analyzer import NewCaesarAnalyzer
from app.solver.new_caesar_solver import NewCaesarSolver

_ALPHABET = "abcdefghijklmnop"
_SHUFFLED_ALPHABET = "plkjihgfedcbanom"
_FLAG = "picoCTF{new_caesar_b16_ok}"


def _b16_encode(value: str, alphabet: str) -> str:
    chars = []
    for byte in value.encode("utf-8"):
        chars.append(alphabet[byte >> 4])
        chars.append(alphabet[byte & 0xF])
    return "".join(chars)


def _encrypt(plaintext: str, alphabet: str, key: int) -> str:
    b16 = _b16_encode(plaintext, alphabet)
    index = {char: position for position, char in enumerate(alphabet)}
    return "".join(alphabet[(index[char] + key) % 16] for char in b16)


def _source(alphabet: str = _ALPHABET) -> str:
    return (
        "import random\n"
        f'ALPHABET = "{alphabet}"\n'
        "LOWERCASE_OFFSET = ord('a')\n"
        "def b16_encode(s):\n"
        "    ret = ''\n"
        "    for c in s:\n"
        "        ret += ALPHABET[ord(c) // 16] + ALPHABET[ord(c) % 16]\n"
        "    return ret\n"
        "def shift(c, k):\n"
        "    return ALPHABET[(ALPHABET.index(c) + k) % 16]\n"
    )


def _file(name: str, *, text_content: str | None = None, strings: list[str] | None = None):
    content = text_content or ""
    return FileAnalysisResult(
        name, len(content), Path(name).suffix, "text", text_content, strings or []
    )


def _challenge(*files: FileAnalysisResult, question: str = "復号してください") -> ChallengeInput:
    return ChallengeInput(question=question, files=list(files))


def test_normal_decode_returns_flag_candidate():
    ciphertext = _encrypt(_FLAG, _ALPHABET, key=5)
    challenge = _challenge(
        _file("chal.py", text_content=_source()),
        _file("output.txt", text_content=ciphertext),
    )
    result = NewCaesarAnalyzer().analyze(challenge)
    assert result is not None
    flags = [c.plaintext for c in result.candidates if c.contains_flag]
    assert _FLAG in flags


def test_key_brute_force_tries_all_sixteen_keys(monkeypatch):
    ciphertext = _encrypt(_FLAG, _ALPHABET, key=11)
    solver = NewCaesarSolver()
    attempted_keys: list[int] = []
    original_decode = NewCaesarSolver._decode

    def _tracking_decode(ciphertext_arg, alphabet_arg, index_arg, key_arg):
        attempted_keys.append(key_arg)
        return original_decode(ciphertext_arg, alphabet_arg, index_arg, key_arg)

    monkeypatch.setattr(NewCaesarSolver, "_decode", staticmethod(_tracking_decode))

    result = solver.solve(ciphertext, _ALPHABET, "test")

    assert attempted_keys == list(range(16))
    match = next(c for c in result.candidates if c.contains_flag)
    assert match.key == 11
    assert match.plaintext == _FLAG


def test_picoctf_like_two_file_challenge_is_solved_without_ai(tmp_path: Path):
    ciphertext = _encrypt(_FLAG, _ALPHABET, key=3)
    source_path = tmp_path / "chal.py"
    source_path.write_text(_source(), encoding="utf-8")
    output_path = tmp_path / "output.txt"
    output_path.write_text(ciphertext, encoding="utf-8")

    controller = MagicMock()
    analyzer = MagicMock()
    analyzer.analyze.return_value = "Crypto"
    service = ChallengeService(controller=controller, analyzer=analyzer)

    result = service.solve("new_caesarを解いてください", [source_path, output_path])

    assert result.flag == _FLAG
    assert result.confidence == 90
    assert "New Caesar" in (result.reason or "")
    assert "鍵：3" in (result.reason or "")
    controller.process_challenge.assert_not_called()


def test_no_flag_present_returns_candidates_without_flag():
    ciphertext = _encrypt("no flag here just text", _ALPHABET, key=2)
    challenge = _challenge(
        _file("chal.py", text_content=_source()),
        _file("output.txt", text_content=ciphertext),
    )
    result = NewCaesarAnalyzer().analyze(challenge)
    assert result is not None
    assert all(not c.contains_flag for c in result.candidates)


def test_missing_python_markers_does_not_run_solver():
    challenge = _challenge(
        _file("readme.txt", text_content="this is unrelated plain text with no markers"),
        _file("output.txt", text_content=_encrypt(_FLAG, _ALPHABET, key=4)),
    )
    result = NewCaesarAnalyzer().analyze(challenge)
    assert result is None


def test_alphabet_change_still_decodes_correctly():
    assert len(set(_SHUFFLED_ALPHABET)) == 16
    ciphertext = _encrypt(_FLAG, _SHUFFLED_ALPHABET, key=9)
    challenge = _challenge(
        _file("chal.py", text_content=_source(_SHUFFLED_ALPHABET)),
        _file("output.txt", text_content=ciphertext),
    )
    result = NewCaesarAnalyzer().analyze(challenge)
    assert result is not None
    flags = [c.plaintext for c in result.candidates if c.contains_flag]
    assert _FLAG in flags


def test_duplicate_flag_candidates_are_deduplicated():
    ciphertext = _encrypt(_FLAG, _ALPHABET, key=6)
    challenge = _challenge(
        _file("chal.py", text_content=_source()),
        _file(
            "output.txt",
            text_content=ciphertext,
            strings=[ciphertext],
        ),
    )
    result = NewCaesarAnalyzer().analyze(challenge)
    assert result is not None
    matches = [c for c in result.candidates if c.contains_flag]
    assert len(matches) == 1


def test_ai_is_never_invoked_by_solver_or_analyzer():
    analyzer_module_source = Path("app/solver/new_caesar_analyzer.py").read_text(
        encoding="utf-8"
    )
    solver_module_source = Path("app/solver/new_caesar_solver.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("subprocess", "exec(", "eval(", "Controller", "api_key"):
        assert forbidden not in analyzer_module_source
        assert forbidden not in solver_module_source
