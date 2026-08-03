import base64
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.agents.agent_input import AgentInput
from app.agents.crypto_agent import CryptoAgent
from app.challenge.challenge_context_builder import ChallengeContextBuilder
from app.challenge.challenge_input import ChallengeInput
from app.challenge.challenge_service import ChallengeService
from app.client.base_client import BaseAIClient
from app.file.file_analysis_result import FileAnalysisResult
from app.file.file_input import FileInput
from app.file.static_file_analyzer import StaticFileAnalyzer
from app.solver.recursive_encoding_analyzer import (
    MAX_RECURSIVE_ENCODING_DEPTH,
    MAX_RECURSIVE_ENCODING_INPUT,
    RecursiveEncodingAnalyzer,
)
from app.solver.recursive_encoding_result import MAX_RECURSIVE_ENCODING_STEPS

CYLAB_INPUT = (
    "YidkM0JxZGtwQlRYdHFhR3g2YUhsZmF6TnFlVGwzWVROclgyeG9OakJzTURCcGZRPT0nCg=="
)
EXPECTED_FLAG = "picoCTF{caesar_d3cr9pt3d_ea60e00b}"


class RecordingFakeAIClient(BaseAIClient):
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "固定AI回答"


def _encoded(value: str, times: int = 1) -> str:
    for _ in range(times):
        value = base64.b64encode(value.encode()).decode()
    return value


def _result(value: str, *, in_strings: bool = False):
    return RecursiveEncodingAnalyzer().analyze(
        text_content=None if in_strings else value,
        strings=[value] if in_strings else [],
    )


def test_one_and_two_layer_base64_detect_flags():
    one = _result(_encoded("FLAG{one}"))
    two = _result(_encoded(_encoded("FLAG{two}")))
    assert one is not None and one.flag_candidates == ("FLAG{one}",)
    assert two is not None and two.flag_candidates == ("FLAG{two}",)
    assert [step.depth for step in two.steps if step.method == "base64"] == [1, 2]


@pytest.mark.parametrize("quote", ["'", '"'])
def test_python_bytes_literal_is_normalized_without_evaluation(quote: str):
    value = f"b{quote}{_encoded('FLAG{bytes}')}{quote}"
    result = _result(value)
    assert result is not None
    assert result.flag_candidates == ("FLAG{bytes}",)
    assert result.steps[0].method == "python_bytes_literal"


def test_cylab_recursive_base64_bytes_literal_and_caesar_path():
    result = _result(CYLAB_INPUT)
    assert result is not None
    assert EXPECTED_FLAG in result.flag_candidates
    assert [step.method for step in result.steps] == [
        "base64",
        "python_bytes_literal",
        "base64",
        "caesar",
    ]
    flag_step = next(step for step in result.steps if step.flag_candidate == EXPECTED_FLAG)
    assert flag_step.depth == 2
    assert flag_step.caesar_shift == 7


def test_text_and_strings_sources_and_input_order_are_preserved():
    text = _encoded("FLAG{text_source}")
    string = _encoded("FLAG{string_source}")
    result = RecursiveEncodingAnalyzer().analyze(
        text_content=text,
        strings=[string, string],
    )
    assert result is not None
    assert result.flag_candidates == ("FLAG{text_source}", "FLAG{string_source}")
    assert [step.source for step in result.steps] == ["text_content", "strings[0]"]


@pytest.mark.parametrize(
    "value",
    ["", "not base64!", "b'incomplete\"", "//8=", "abc"],
)
def test_invalid_empty_incomplete_and_non_utf8_inputs_are_ignored(value: str):
    assert _result(value) is None


def test_depth_step_and_input_limits_are_bounded():
    too_deep = _result(_encoded(_encoded(_encoded(_encoded("FLAG{deep}")))))
    assert too_deep is not None
    assert max(step.depth for step in too_deep.steps) == MAX_RECURSIVE_ENCODING_DEPTH
    assert "FLAG{deep}" not in too_deep.flag_candidates
    many = RecursiveEncodingAnalyzer().analyze(
        text_content=None,
        strings=[_encoded(f"FLAG{{item_{index}}}") for index in range(150)],
    )
    assert many is not None
    assert len(many.steps) <= MAX_RECURSIVE_ENCODING_STEPS
    assert many.truncated is True
    long_result = _result("A" * (MAX_RECURSIVE_ENCODING_INPUT + 1))
    assert long_result is not None and long_result.truncated is True


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit()])
def test_process_control_exceptions_are_not_swallowed(monkeypatch, error):
    analyzer = RecursiveEncodingAnalyzer()
    monkeypatch.setattr(
        analyzer,
        "_decode_base64",
        lambda _value: (_ for _ in ()).throw(error),
    )
    with pytest.raises(type(error)):
        analyzer.analyze(text_content=_encoded("test"), strings=[])


def test_static_file_analyzer_integrates_without_changing_source_dto():
    content = CYLAB_INPUT.encode()
    file_input = FileInput("challenge.txt", Path("challenge.txt"), len(content), ".txt", content)
    before = (file_input.name, file_input.path, file_input.size, file_input.content)
    result = StaticFileAnalyzer().analyze(file_input)
    assert result.recursive_encoding_result is not None
    assert EXPECTED_FLAG in result.recursive_encoding_result.flag_candidates
    assert before == (file_input.name, file_input.path, file_input.size, file_input.content)


def test_challenge_service_fast_path_avoids_controller_and_ai(tmp_path: Path):
    path = tmp_path / "cylab.txt"
    path.write_text(CYLAB_INPUT, encoding="utf-8")
    controller = MagicMock()
    analyzer = MagicMock()
    analyzer.analyze.return_value = "Crypto"
    service = ChallengeService(controller=controller, analyzer=analyzer)
    result = service.solve("decode attachment", [path])
    assert result.flag == EXPECTED_FLAG
    assert result.confidence == 90
    assert "recursive_encoding" not in (result.reason or "")
    assert "Base64深度=2" in (result.reason or "")
    assert "Caesar shift=7" in (result.reason or "")
    controller.process_challenge.assert_not_called()


def test_context_and_crypto_agent_include_limited_recursive_evidence():
    content = CYLAB_INPUT.encode()
    file_result = StaticFileAnalyzer().analyze(
        FileInput("cylab.txt", Path("cylab.txt"), len(content), ".txt", content)
    )
    challenge = ChallengeInput("decode", [file_result])
    context = ChallengeContextBuilder().build(challenge)
    assert "再帰エンコード解析：" in context
    assert "method=base64" in context
    assert "shift=7" in context
    ai = RecordingFakeAIClient()
    agent_result = CryptoAgent(ai).analyze(
        AgentInput(challenge, "Crypto", context, (), {})
    )
    assert len(ai.prompts) == 1
    assert any(
        evidence.source == "recursive_encoding:cylab.txt"
        for evidence in agent_result.evidence
    )


def test_existing_file_analysis_result_constructor_remains_compatible():
    result = FileAnalysisResult("x", 0, ".bin", "unknown", None, [])
    assert result.recursive_encoding_result is None
