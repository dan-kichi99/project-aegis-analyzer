import inspect
from unittest.mock import MagicMock

import pytest

from app.codegen.code_safety_result import (
    CodeRiskCategory,
    CodeRiskLevel,
)
from app.codegen.generated_code_result import GeneratedCodeStatus
from app.codegen.python_code_safety_analyzer import (
    MAX_FINDINGS,
    PythonCodeSafetyAnalyzer,
)
from app.judge.judge import Judge
from app.utils.result_formatter import ResultFormatter


def _analyze(code: str):
    return PythonCodeSafetyAnalyzer().analyze(code)


def _judge() -> Judge:
    dependencies = [MagicMock() for _ in range(6)]
    dependencies[0].extract.return_value = None
    dependencies[1].estimate.return_value = 40
    dependencies[2].extract.return_value = "reason"
    dependencies[3].extract.return_value = []
    dependencies[4].extract.return_value = None
    dependencies[5].generate.return_value = None
    return Judge(*dependencies)


def _finding(result, symbol: str):
    return next(item for item in result.findings if item.symbol == symbol)


def test_safe_python_is_parseable_without_safety_claim():
    result = _analyze("import math\nprint(math.sqrt(4))")

    assert result.parseable is True
    assert result.overall_risk is CodeRiskLevel.LOW
    assert result.findings == ()


def test_syntax_error_is_blocked_without_escaping_exception():
    result = _analyze("if True print('x')")

    assert result.parseable is False
    assert result.overall_risk is CodeRiskLevel.BLOCKED
    assert result.findings[0].category is CodeRiskCategory.SYNTAX
    assert result.findings[0].line_number == 1


@pytest.mark.parametrize(
    ("code", "symbol", "minimum"),
    [
        ("import subprocess", "subprocess", CodeRiskLevel.BLOCKED),
        ("import subprocess as sp\nsp.run([])", "subprocess.run", CodeRiskLevel.BLOCKED),
        ("from subprocess import run\nrun([])", "subprocess.run", CodeRiskLevel.BLOCKED),
        ("import os", "os", CodeRiskLevel.HIGH),
        ("import os\nos.system('x')", "os.system", CodeRiskLevel.BLOCKED),
        ("import os\nos.remove('x')", "os.remove", CodeRiskLevel.HIGH),
        ("import shutil\nshutil.rmtree('x')", "shutil.rmtree", CodeRiskLevel.HIGH),
        ("from pathlib import Path\nPath('x').unlink()", "pathlib.Path.unlink", CodeRiskLevel.HIGH),
        ("open('x', 'w')", "open", CodeRiskLevel.HIGH),
        ("open('x', 'r')", "open", CodeRiskLevel.MEDIUM),
        ("stream.write('x')", "stream.write", CodeRiskLevel.HIGH),
        ("eval('1')", "eval", CodeRiskLevel.BLOCKED),
        ("exec('x=1')", "exec", CodeRiskLevel.BLOCKED),
        ("compile('x=1', 'x', 'exec')", "compile", CodeRiskLevel.BLOCKED),
        ("__import__('os')", "__import__", CodeRiskLevel.BLOCKED),
        ("import socket\nsocket.socket()", "socket.socket", CodeRiskLevel.BLOCKED),
        ("import requests\nrequests.get('https://example.test')", "requests.get", CodeRiskLevel.HIGH),
        ("import urllib.request\nurllib.request.urlopen('https://example.test')", "urllib.request.urlopen", CodeRiskLevel.HIGH),
        ("import os\nvalue = os.environ", "os.environ", CodeRiskLevel.HIGH),
        ("import os\nos.getenv('TOKEN')", "os.getenv", CodeRiskLevel.HIGH),
        ("globals()", "globals", CodeRiskLevel.MEDIUM),
        ("getattr(object(), 'x')", "getattr", CodeRiskLevel.MEDIUM),
    ],
)
def test_detects_dangerous_symbols(code, symbol, minimum):
    result = _analyze(code)

    assert _finding(result, symbol).risk_level is minimum


@pytest.mark.parametrize("condition", ["True", "1", "99"])
def test_constant_true_while_is_blocked(condition):
    result = _analyze(f"while {condition}:\n    pass")

    assert _finding(result, "while").risk_level is CodeRiskLevel.BLOCKED


def test_break_lowers_constant_while_risk():
    result = _analyze("while True:\n    break")

    assert _finding(result, "while").risk_level is CodeRiskLevel.MEDIUM


def test_for_loop_alone_is_not_blocked():
    assert _analyze("for value in range(3):\n    print(value)").overall_risk is CodeRiskLevel.LOW


@pytest.mark.parametrize(
    "code",
    [
        "action = lambda: eval('1')",
        "values = [eval('1') for _ in range(1)]",
        "@eval('decorator')\ndef target():\n    pass",
        "def target(value=eval('1')):\n    return value",
    ],
)
def test_visits_calls_in_all_ast_contexts(code):
    assert _finding(_analyze(code), "eval").risk_level is CodeRiskLevel.BLOCKED


def test_findings_are_deduplicated_and_deterministically_sorted():
    code = "import os\nos.getenv('X')\nos.remove('x')"

    first = _analyze(code).findings
    second = _analyze(code).findings

    assert first == second
    keys = [(item.line_number, item.category, item.symbol) for item in first]
    assert len(keys) == len(set(keys))
    assert [item.line_number for item in first] == sorted(item.line_number for item in first)


def test_findings_are_limited_to_one_hundred():
    code = "\n".join(f"eval('{index}')" for index in range(MAX_FINDINGS + 20))

    assert len(_analyze(code).findings) == MAX_FINDINGS


def test_judge_attaches_safety_without_changing_code_or_status():
    code = "import subprocess\nsubprocess.run([])"
    result = _judge().evaluate("Rev", f"```python\n{code}\n```")

    item = result.generated_code.items[0]
    assert item.code == code
    assert item.status is GeneratedCodeStatus.REVIEW_REQUIRED
    assert item.safety.overall_risk is CodeRiskLevel.BLOCKED


def test_unknown_candidate_is_blocked_and_not_treated_as_executable():
    result = _judge().evaluate("Misc", "```\nvalue = 123\n```")

    item = result.generated_code.items[0]
    assert item.safety.parseable is False
    assert item.safety.overall_risk is CodeRiskLevel.BLOCKED
    assert item.status is GeneratedCodeStatus.REVIEW_REQUIRED


def test_formatter_shows_risk_findings_and_static_analysis_warning():
    result = _judge().evaluate("Rev", "```python\nimport subprocess\n```")

    output = ResultFormatter().format(result)

    assert "安全性検査：" in output
    assert "総合危険度：実行禁止" in output
    assert "subprocess" in output
    assert "静的検査だけではコードの安全性を保証できません。" in output
    assert "現在、このコードは実行できません。" in output


def test_formatter_reports_no_detected_findings_without_calling_code_safe():
    result = _judge().evaluate("Rev", "```python\nprint('hello')\n```")

    output = ResultFormatter().format(result)

    assert "総合危険度：低" in output
    assert "検出された危険項目はありません。" in output
    assert "安全です" not in output
    assert "実行して問題ありません" not in output


def test_analyzer_never_executes_or_uses_processes():
    source = inspect.getsource(PythonCodeSafetyAnalyzer)

    assert "ast.parse" in source
    assert "subprocess" not in source
    assert "eval(" not in source
    assert "exec(" not in source
