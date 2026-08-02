import inspect
from unittest.mock import MagicMock

import pytest

from app.codegen.code_block_extractor import (
    MAX_BLOCK_CHARACTERS,
    MAX_CODE_BLOCKS,
    MAX_PURPOSE_CHARACTERS,
    MAX_TOTAL_CHARACTERS,
    CodeBlockExtractor,
)
from app.codegen.generated_code_result import (
    GeneratedCode,
    GeneratedCodeLanguage,
    GeneratedCodeResult,
    GeneratedCodeStatus,
)
from app.judge.judge import Judge
from app.judge.judge_result import JudgeResult
from app.utils.result_formatter import ResultFormatter


def _extract(response: str) -> GeneratedCodeResult:
    return CodeBlockExtractor().extract(response)


def _judge() -> Judge:
    flag_extractor = MagicMock()
    flag_extractor.extract.side_effect = lambda response: (
        "FLAG{code}" if "FLAG{code}" in response else None
    )
    confidence = MagicMock()
    confidence.estimate.return_value = 50
    reason = MagicMock()
    reason.extract.return_value = "reason"
    actions = MagicMock()
    actions.extract.return_value = ["review"]
    hypothesis = MagicMock()
    hypothesis.extract.return_value = "hypothesis"
    gemini = MagicMock()
    gemini.generate.return_value = "prompt"
    return Judge(
        flag_extractor=flag_extractor,
        confidence_estimator=confidence,
        reason_extractor=reason,
        next_action_extractor=actions,
        hypothesis_extractor=hypothesis,
        gemini_prompt_generator=gemini,
    )


@pytest.mark.parametrize("label", ["python", "py", "Python", "PYTHON", "Py"])
def test_extracts_supported_python_labels_case_insensitively(label):
    result = _extract(f"```{label}\nprint('test')\n```")

    assert len(result.items) == 1
    assert result.items[0].language is GeneratedCodeLanguage.PYTHON
    assert result.items[0].code == "print('test')"
    assert result.items[0].status is GeneratedCodeStatus.REVIEW_REQUIRED


def test_multiple_blocks_keep_order_and_original_source_indexes():
    response = (
        "```python\nprint('first')\n```\n"
        "```javascript\nconsole.log('ignored')\n```\n"
        "```py\nprint('third')\n```"
    )

    result = _extract(response)

    assert [item.code for item in result.items] == [
        "print('first')",
        "print('third')",
    ]
    assert [item.source_index for item in result.items] == [0, 2]


def test_normalizes_newlines_and_removes_only_trailing_newlines():
    result = _extract(
        "```python\r\nif True:\r\n    print('x')\r\n\r\n```"
    )

    assert result.items[0].code == "if True:\n    print('x')"


def test_preserves_indentation_comments_and_inline_backticks():
    code = "def run():\n    # keep comment\n    value = '```'\n    return value"

    result = _extract(f"```python\n{code}\n```")

    assert result.items[0].code == code


def test_empty_and_whitespace_only_blocks_are_ignored():
    assert _extract("```python\n\n```").items == ()
    assert _extract("```py\n   \n```").items == ()


def test_unclosed_fence_is_ignored_safely():
    assert _extract("before\n```python\nprint('never closed')").items == ()


@pytest.mark.parametrize("label", ["javascript", "bash", "powershell", "c", "rust"])
def test_non_python_labeled_blocks_are_not_python_candidates(label):
    assert _extract(f"```{label}\nprint('test')\n```").items == ()


def test_unlabeled_python_like_block_is_detected():
    result = _extract("```\nimport base64\nprint(base64.b64decode(data))\n```")

    assert result.items[0].language is GeneratedCodeLanguage.PYTHON


def test_ambiguous_unlabeled_block_is_unknown():
    result = _extract("```\nvalue = 123\n```")

    assert result.items[0].language is GeneratedCodeLanguage.UNKNOWN


def test_limits_number_of_blocks_to_five():
    response = "\n".join(
        f"```python\nprint({index})\n```" for index in range(8)
    )

    result = _extract(response)

    assert len(result.items) == MAX_CODE_BLOCKS
    assert [item.source_index for item in result.items] == list(range(5))


def test_rejects_block_over_per_block_limit():
    oversized = "x" * (MAX_BLOCK_CHARACTERS + 1)

    assert _extract(f"```python\n{oversized}\n```").items == ()


def test_total_character_limit_rejects_excess_blocks():
    first = "a" * MAX_BLOCK_CHARACTERS
    second = "b" * MAX_BLOCK_CHARACTERS
    third = "c" * (MAX_TOTAL_CHARACTERS - len(first) - len(second) + 1)
    response = (
        f"```python\n{first}\n```\n"
        f"```python\n{second}\n```\n"
        f"```python\n{third}\n```"
    )

    result = _extract(response)

    assert len(result.items) == 2
    assert sum(len(item.code) for item in result.items) <= MAX_TOTAL_CHARACTERS


def test_extracts_immediate_previous_explanation_as_purpose():
    result = _extract(
        "次のスクリプトでXORを復号できます。\n\n"
        "```python\nprint('decode')\n```"
    )

    assert result.items[0].purpose == "次のスクリプトでXORを復号できます。"


def test_purpose_is_limited_and_not_reused_for_next_block():
    explanation = "説" * (MAX_PURPOSE_CHARACTERS + 20)
    response = (
        f"{explanation}\n```python\nprint(1)\n```\n"
        "```python\nprint(2)\n```"
    )

    result = _extract(response)

    assert result.items[0].purpose == explanation[:MAX_PURPOSE_CHARACTERS]
    assert result.items[1].purpose is None


def test_judge_stores_generated_code_without_changing_answer():
    response = "説明\n```python\nprint('candidate')\n```"

    result = _judge().evaluate("Crypto", response)

    assert result.answer == response
    assert result.generated_code is not None
    assert result.generated_code.items[0].code == "print('candidate')"


def test_judge_uses_none_when_no_code_exists():
    result = _judge().evaluate("Crypto", "No code response")

    assert result.generated_code is None


def test_existing_flag_consistency_is_preserved_with_code():
    result = _judge().evaluate(
        "Crypto",
        "FLAG{code}\n```python\nprint('candidate')\n```",
    )

    assert result.flag == "FLAG{code}"
    assert result.confidence == 90
    assert result.hypothesis is None
    assert result.next_actions == []
    assert result.gemini_prompt is None
    assert result.generated_code is not None


def test_local_result_defaults_generated_code_to_none():
    result = JudgeResult(
        category="Misc",
        answer="ローカル解析結果",
        flag="FLAG{local}",
    )

    assert result.generated_code is None


def test_formatter_displays_review_required_unexecuted_candidate():
    generated = GeneratedCodeResult(
        items=(
            GeneratedCode(
                language=GeneratedCodeLanguage.PYTHON,
                code="print('safe display')",
                purpose="XOR復号を試す",
                source_index=0,
                status=GeneratedCodeStatus.REVIEW_REQUIRED,
            ),
        )
    )
    result = JudgeResult(
        category="Crypto",
        answer="AI response",
        generated_code=generated,
    )

    output = ResultFormatter().format(result)

    assert "生成コード候補" in output
    assert "候補 1" in output
    assert "言語：Python" in output
    assert "状態：要レビュー" in output
    assert "目的：XOR復号を試す" in output
    assert "print('safe display')" in output
    assert "このコードはまだ実行されていません。" in output
    assert "内容を確認してから実行してください。" in output


def test_formatter_omits_generated_section_without_items():
    without_result = JudgeResult(category="Misc", answer="answer")
    empty_result = JudgeResult(
        category="Misc",
        answer="answer",
        generated_code=GeneratedCodeResult(items=()),
    )

    assert "生成コード候補" not in ResultFormatter().format(without_result)
    assert "生成コード候補" not in ResultFormatter().format(empty_result)


def test_dangerous_looking_code_is_only_extracted_and_never_executed():
    response = (
        "```python\n"
        "import os, subprocess, socket\n"
        "os.remove('file')\n"
        "eval('1 + 1')\n"
        "exec('while True: pass')\n"
        "```"
    )

    result = _extract(response)

    assert result.items[0].code.startswith("import os, subprocess, socket")
    source = inspect.getsource(CodeBlockExtractor)
    assert "subprocess.run" not in source
    assert "subprocess.Popen" not in source
    assert "exec(" not in source
    assert "eval(" not in source
