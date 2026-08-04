from dataclasses import fields
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.challenge.challenge_input import ChallengeInput
from app.challenge.challenge_service import ChallengeService
from app.file.file_analysis_result import FileAnalysisResult
from app.judge.flag_extractor import FlagExtractor
from app.solver.java_source_analyzer import JavaSourceAnalyzer
from app.solver.java_source_result import (
    MAX_JAVA_SOURCE_CANDIDATES,
    JavaSourceCandidate,
)
from app.solver.java_source_solver import (
    MAX_JAVA_SOURCE_INPUT,
    JavaSourceSolver,
)

BODY = "w4rm1ng_Up_w1tH_jAv4_000HPpgh7Ph"
FLAG = f"picoCTF{{{BODY}}}"


def _java(compare: str, prefix: str = "picoCTF{") -> str:
    return f'''public class Vault {{
    public static boolean check(String userInput) {{
        String password = userInput.substring("{prefix}".length(), userInput.length() - 1);
        return {compare};
    }}
}}'''


def _file(name: str, text: str | None = None, strings=None):
    return FileAnalysisResult(name, len(text or ""), Path(name).suffix, "text", text, strings or [])


@pytest.mark.parametrize(
    ("comparison", "method"),
    [
        (f'password.equals("{BODY}")', "java_equals"),
        (f'"{BODY}".equals(password)', "java_equals"),
        (f'password.equalsIgnoreCase("{BODY}")', "java_equals_ignore_case"),
        (f'"{BODY}".equalsIgnoreCase(password)', "java_equals_ignore_case"),
    ],
)
def test_equals_forms_extract_body_and_build_flag(comparison: str, method: str):
    result = JavaSourceSolver().solve(_java(comparison), "Vault.java")
    assert result is not None
    candidate = result.candidates[0]
    assert candidate.body == BODY
    assert candidate.prefix == "picoCTF{"
    assert candidate.flag_candidate == FLAG
    assert candidate.method == method
    assert candidate.line_number == 4


def test_vault_door_training_source_is_solved_statically():
    source = _java(f'password.equals("{BODY}")')
    result = JavaSourceAnalyzer().analyze(
        ChallengeInput("solve", [_file("VaultDoorTraining.java", source)])
    )
    assert result is not None
    assert result.candidates[0].flag_candidate == FLAG


def test_question_text_content_and_strings_sources_are_supported_in_order():
    values = (
        _java('password.equals("question")', "FLAG{"),
        _java('password.equals("text")', "CTF{"),
        _java('password.equals("strings")', "HTB{"),
    )
    result = JavaSourceAnalyzer().analyze(
        ChallengeInput(
            values[0],
            [_file("Vault.java", values[1], [values[2]])],
        )
    )
    assert result is not None
    assert [item.flag_candidate for item in result.candidates] == [
        "FLAG{question}", "CTF{text}", "HTB{strings}",
    ]
    assert [item.source for item in result.candidates] == [
        "question", "Vault.java", "Vault.java:strings[0]",
    ]


def test_java_extension_is_strong_evidence_but_non_java_needs_two_markers():
    minimal = 'value.equals("secret")'
    assert JavaSourceSolver().solve(minimal, "Vault.java", java_extension=True) is not None
    assert JavaSourceSolver().solve(minimal, "question") is None
    detected = JavaSourceSolver().solve("class X { return value.equals(\"secret\"); }", "question")
    assert detected is not None


def test_multiple_candidates_keep_appearance_order_and_are_deduplicated():
    source = _java(
        'password.equals("first") || password.equals("first") || password.equals("second")',
        "FLAG{",
    )
    result = JavaSourceSolver().solve(source, "Vault.java")
    assert result is not None
    assert [item.body for item in result.candidates] == ["first", "second"]


@pytest.mark.parametrize("comment", ["//", "/*", "/**"])
def test_equals_inside_comments_is_ignored(comment: str):
    closing = "" if comment == "//" else " */"
    source = f'public class X {{\n{comment} password.equals("fake"){closing}\nreturn true;\n}}'
    assert JavaSourceSolver().solve(source, "X.java", java_extension=True) is None


def test_comment_tokens_inside_string_literals_are_not_treated_as_comments():
    for body in ("http://example.com", "/* not comment */", "// not comment"):
        source = _java(f'password.equals("{body}")', "FLAG{")
        result = JavaSourceSolver().solve(source, "Vault.java")
        assert result is not None and result.candidates[0].body == body


@pytest.mark.parametrize(
    "source",
    [
        'public class X { System.out.println("Access granted."); }',
        'plain text password.equals("secret")',
        'public class X { return password.equals("unterminated); }',
        'public class X { return true; }',
        '',
    ],
)
def test_logs_non_java_incomplete_and_empty_inputs_do_not_create_candidates(source: str):
    assert JavaSourceSolver().solve(source, "input") is None


def test_substring_prefix_fragment_is_not_reported_as_a_flag():
    source = _java(f'password.equals("{BODY}")')
    assert FlagExtractor().extract(source) is None
    result = JavaSourceSolver().solve(source, "Vault.java")
    assert result is not None and result.candidates[0].flag_candidate == FLAG


@pytest.mark.parametrize(
    "flag",
    [
        "picoCTF{abc}", "FLAG{abc}", "CTF{abc}", "HTB{abc}",
        "DUCTF{abc}", "AIS3{abc}", "SECCON{abc}", "TSGCTF{abc}",
        "TCP1P{abc}",
    ],
)
def test_existing_flag_prefixes_remain_supported(flag: str):
    assert FlagExtractor().extract(flag) == flag


def test_candidate_and_input_limits_are_enforced():
    comparisons = " || ".join(
        f'password.equals("item_{index}")' for index in range(150)
    )
    result = JavaSourceSolver().solve(_java(comparisons, "FLAG{"), "Vault.java")
    assert result is not None
    assert len(result.candidates) == MAX_JAVA_SOURCE_CANDIDATES
    assert result.truncated is True
    long_source = _java(f'password.equals("{BODY}")') + " " * MAX_JAVA_SOURCE_INPUT
    limited = JavaSourceSolver().solve(long_source, "Vault.java")
    assert limited is not None and limited.truncated is True


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit()])
def test_process_control_exceptions_propagate(monkeypatch, error):
    solver = JavaSourceSolver()
    monkeypatch.setattr(
        solver,
        "_remove_comments",
        lambda _text: (_ for _ in ()).throw(error),
    )
    with pytest.raises(type(error)):
        solver.solve(_java('password.equals("x")'), "Vault.java")


def test_challenge_service_fast_path_avoids_controller_and_ai(tmp_path: Path):
    path = tmp_path / "VaultDoorTraining.java"
    path.write_text(_java(f'password.equals("{BODY}")'), encoding="utf-8")
    controller = MagicMock()
    category = MagicMock()
    category.analyze.return_value = "Rev"
    service = ChallengeService(controller=controller, analyzer=category)
    execution = service.solve_with_usage("solve Java challenge", [path])
    assert execution.result.flag == FLAG
    assert execution.result.confidence == 90
    assert "java_equals" in (execution.result.reason or "")
    assert "VaultDoorTraining.java" in (execution.result.reason or "")
    assert execution.ai_usage.local_solution_avoided_ai is True
    assert execution.analysis_context != ""
    assert BODY in execution.analysis_context
    controller.process_challenge.assert_not_called()
    controller.process_challenge_with_usage.assert_not_called()


def test_dto_is_frozen_slotted_and_source_inputs_are_not_modified():
    source = _java('password.equals("stable")', "FLAG{")
    challenge = ChallengeInput(source, [_file("Stable.java", source)])
    before = (challenge.question, challenge.files[0].text_content)
    result = JavaSourceAnalyzer().analyze(challenge)
    assert result is not None
    assert before == (challenge.question, challenge.files[0].text_content)
    with pytest.raises((AttributeError, TypeError)):
        result.candidates[0].body = "changed"
    assert {field.name for field in fields(JavaSourceCandidate)} == {
        "source", "prefix", "body", "flag_candidate", "method",
        "confidence", "line_number", "evidence_preview", "truncated",
    }


def test_no_files_execution_ai_network_or_external_tools_are_used():
    source = "".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "app/solver/java_source_solver.py",
            "app/solver/java_source_analyzer.py",
        )
    )
    for forbidden in (
        "subprocess", "javac", "os.system", "OpenAI", "requests",
        "socket.", "shell=True", "\nexec(", "\neval(", "\ncompile(",
    ):
        assert forbidden not in source
