import base64
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.challenge.challenge_input import ChallengeInput
from app.challenge.challenge_service import ChallengeService
from app.file.file_analysis_result import FileAnalysisResult
from app.solver.python_source_analyzer import PythonSourceAnalyzer
from app.solver.python_source_result import MAX_PYTHON_SOURCE_CANDIDATES
from app.solver.python_source_solver import (
    MAX_PYTHON_EVALUATION_DEPTH,
    MAX_PYTHON_SOURCE_INPUT,
    PythonSourceSolver,
)


def _solve(source: str, *, extension: bool = True):
    return PythonSourceSolver().solve(source, "solve.py", python_extension=extension)


def _file(name: str, text: str | None = None, strings=None):
    return FileAnalysisResult(name, len(text or ""), Path(name).suffix, "text", text, strings or [])


@pytest.mark.parametrize(
    ("source", "flag", "method"),
    [
        ('flag = "CTF{direct}"', "CTF{direct}", "python_direct_flag"),
        ('FLAG = "HCSCTF{unknown}"', "HCSCTF{unknown}", "python_direct_flag"),
        ('flag = "pico" + "CTF{" + "concat" + "}"', "picoCTF{concat}", "python_string_concat"),
        ('flag = "}esrever{FTCocip"[::-1]', "picoCTF{reverse}", "python_reverse"),
        ('flag = chr(70) + chr(76) + chr(65) + chr(71) + "{chr}"', "FLAG{chr}", "python_string_concat"),
        ('flag = "".join(chr(x) for x in [70,76,65,71,123,106,111,105,110,125])', "FLAG{join}", "python_chr_join"),
        ('flag = "".join([chr(70), chr(76), chr(65), chr(71), chr(123), chr(120), chr(125)])', "FLAG{x}", "python_chr_join"),
        ('flag = bytes([70,76,65,71,123,98,121,116,101,115,125]).decode()', "FLAG{bytes}", "python_bytes"),
        ('flag = bytearray([67,84,70,123,98,97,125]).decode("utf-8")', "CTF{ba}", "python_bytes"),
        ('flag = bytes.fromhex("464c41477b6865787d").decode()', "FLAG{hex}", "python_fromhex"),
    ],
)
def test_static_expression_patterns(source: str, flag: str, method: str):
    result = _solve(source)
    assert result is not None
    assert result.candidates[0].flag_candidate == flag
    assert result.candidates[0].method == method


def test_dynamic_prefix_variable_body_and_startswith_inference():
    source = '''prefix = "MYCTF{"
user_input = input()
valid = user_input.startswith("MYCTF{")
body = "dynamic_body"
flag = prefix + body + "}"'''
    result = _solve(source)
    assert result is not None
    assert result.candidates[0].flag_candidate == "MYCTF{dynamic_body}"
    assert result.candidates[0].prefix == "MYCTF{"


def test_len_prefix_slice_pattern_infers_unknown_prefix_for_body():
    source = '''prefix = "corctf{"
value = input()
body = value[len(prefix):-1]
secret = "slice_body"'''
    result = _solve(source)
    assert result is not None
    assert result.candidates[0].flag_candidate == "corctf{slice_body}"


@pytest.mark.parametrize(
    ("function", "encoded", "flag"),
    [
        ("b64decode", base64.b64encode(b"FLAG{b64}").decode(), "FLAG{b64}"),
        ("urlsafe_b64decode", base64.urlsafe_b64encode("FLAG{ÿÿ}".encode()).decode(), "FLAG{ÿÿ}"),
        ("b32decode", base64.b32encode(b"FLAG{b32}").decode(), "FLAG{b32}"),
        ("b85decode", base64.b85encode(b"FLAG{b85}").decode(), "FLAG{b85}"),
        ("a85decode", base64.a85encode(b"FLAG{a85}").decode(), "FLAG{a85}"),
    ],
)
def test_base_family_calls_reuse_bounded_decoder(function: str, encoded: str, flag: str):
    result = _solve(f'flag = base64.{function}("{encoded}").decode()')
    assert result is not None
    assert result.candidates[0].flag_candidate == flag
    assert result.candidates[0].method == "python_base64"


def test_limited_single_key_xor_pattern():
    flag = b"FLAG{xor}"
    encrypted = [value ^ 42 for value in flag]
    source = f'''encrypted = {encrypted}
key = 42
flag = bytes(x ^ key for x in encrypted).decode()'''
    result = _solve(source)
    assert result is not None
    assert result.candidates[0].flag_candidate == "FLAG{xor}"
    assert result.candidates[0].method == "python_xor"


def test_question_text_strings_sources_preserve_order_and_deduplicate():
    challenge = ChallengeInput(
        'def solve():\n    flag = "FLAG{question}"\n    return flag',
        [_file("solve.py", 'flag = "CTF{text}"', ['flag = "HTB{strings}"', 'flag = "HTB{strings}"'])],
    )
    result = PythonSourceAnalyzer().analyze(challenge)
    assert result is not None
    assert [item.flag_candidate for item in result.candidates] == [
        "FLAG{question}", "CTF{text}", "HTB{strings}",
    ]
    assert [item.source for item in result.candidates] == [
        "question", "solve.py", "solve.py:strings[0]",
    ]


def test_py_extension_is_strong_evidence_and_plain_text_is_not_python():
    assert _solve('flag = "FLAG{x}"') is not None
    assert PythonSourceSolver().solve('flag = "FLAG{x}"', "question") is None
    detected = PythonSourceSolver().solve('def x():\n    return "x"\nflag = "FLAG{x}"', "question")
    assert detected is not None


@pytest.mark.parametrize(
    "source",
    [
        '# flag = "FLAG{comment}"',
        '"""flag = "FLAG{docstring}"""',
        'print("Use FLAG{example} as the format")',
        'example = "picoCTF{not_the_answer}"',
        'prefix = "CTF{"',
        'value = "# not comment"',
        '',
        'flag = "unterminated',
    ],
)
def test_comments_docs_logs_examples_prefixes_and_invalid_inputs_are_ignored(source: str):
    assert _solve(source) is None


@pytest.mark.parametrize(
    "source",
    [
        'flag = bytes([256]).decode()',
        'flag = chr(0x110000)',
        'flag = bytes([255]).decode()',
        'flag = dangerous()',
        'flag = value[1:3]',
        'flag = bytes(x ^ make_key() for x in [1,2]).decode()',
    ],
)
def test_out_of_range_dynamic_and_unsupported_ast_are_ignored(source: str):
    assert _solve(source) is None


def test_candidate_input_and_evaluation_limits_are_bounded():
    source = "\n".join(f'flag_{index} = "FLAG{{item_{index}}}"' for index in range(150))
    result = _solve(source)
    assert result is not None
    assert len(result.candidates) == MAX_PYTHON_SOURCE_CANDIDATES
    assert result.truncated is True
    long_result = _solve('flag = "FLAG{x}"\n' + "#" * MAX_PYTHON_SOURCE_INPUT)
    assert long_result is not None and long_result.truncated is True
    assert MAX_PYTHON_EVALUATION_DEPTH == 10


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit()])
def test_process_control_exceptions_propagate(monkeypatch, error):
    monkeypatch.setattr(
        "ast.parse",
        lambda _text: (_ for _ in ()).throw(error),
    )
    with pytest.raises(type(error)):
        _solve('flag = "FLAG{x}"')


def test_challenge_service_fast_path_avoids_controller_and_ai(tmp_path: Path):
    path = tmp_path / "solve.py"
    path.write_text('flag = "pico" + "CTF{" + "local" + "}"', encoding="utf-8")
    controller = MagicMock()
    category = MagicMock()
    category.analyze.return_value = "Crypto"
    execution = ChallengeService(controller, category).solve_with_usage("solve", [path])
    assert execution.result.flag == "picoCTF{local}"
    assert execution.result.confidence == 90
    assert "python_string_concat" in (execution.result.reason or "")
    assert "solve.py" in (execution.result.reason or "")
    assert execution.ai_usage.local_solution_avoided_ai is True
    controller.process_challenge.assert_not_called()
    controller.process_challenge_with_usage.assert_not_called()


def test_source_and_dto_are_not_mutated_and_no_execution_dependencies_exist():
    source = 'flag = "FLAG{stable}"'
    challenge = ChallengeInput("solve", [_file("stable.py", source)])
    before = challenge.files[0].text_content
    assert PythonSourceAnalyzer().analyze(challenge) is not None
    assert challenge.files[0].text_content == before
    module_source = Path("app/solver/python_source_solver.py").read_text(encoding="utf-8")
    for forbidden in (
        "subprocess", "os.system", "OpenAI", "requests", "socket.",
        "\neval(", "\nexec(", "\ncompile(", "ast.literal_eval",
    ):
        assert forbidden not in module_source
