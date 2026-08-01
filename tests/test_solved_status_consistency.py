from unittest.mock import MagicMock

from app.judge.judge import Judge
from app.judge.judge_result import JudgeResult
from app.utils.result_formatter import ResultFormatter


def _create_mocked_judge() -> Judge:
    flag_extractor = MagicMock()
    confidence_estimator = MagicMock()
    reason_extractor = MagicMock()
    next_action_extractor = MagicMock()
    hypothesis_extractor = MagicMock()
    gemini_prompt_generator = MagicMock()

    return Judge(
        flag_extractor=flag_extractor,
        confidence_estimator=confidence_estimator,
        reason_extractor=reason_extractor,
        next_action_extractor=next_action_extractor,
        hypothesis_extractor=hypothesis_extractor,
        gemini_prompt_generator=gemini_prompt_generator,
    )


def test_judge_flag_found_consistency():
    judge = _create_mocked_judge()

    judge._flag_extractor.extract.return_value = (
        "FLAG{test_solved}"
    )
    judge._confidence_estimator.estimate.return_value = 50
    judge._reason_extractor.extract.return_value = (
        "Extracted reason"
    )
    judge._next_action_extractor.extract.return_value = [
        "Action 1"
    ]
    judge._hypothesis_extractor.extract.return_value = (
        "Hypothesis 1"
    )
    judge._gemini_prompt_generator.generate.return_value = (
        "Prompt text"
    )

    result = judge.evaluate(
        category="Crypto",
        response="Response with FLAG{test_solved}",
    )

    assert result.flag == "FLAG{test_solved}"
    assert result.confidence == 90
    assert result.hypothesis is None
    assert result.next_actions == []
    assert result.gemini_prompt is None
    assert result.reason == "Extracted reason"
    assert result.answer == "Response with FLAG{test_solved}"


def test_judge_keeps_confidence_above_90():
    judge = _create_mocked_judge()

    judge._flag_extractor.extract.return_value = (
        "FLAG{high_confidence}"
    )
    judge._confidence_estimator.estimate.return_value = 97
    judge._reason_extractor.extract.return_value = "Reason"
    judge._next_action_extractor.extract.return_value = []
    judge._hypothesis_extractor.extract.return_value = None
    judge._gemini_prompt_generator.generate.return_value = None

    result = judge.evaluate(
        category="Crypto",
        response="FLAG{high_confidence}",
    )

    assert result.confidence == 97


def test_judge_flag_not_found_consistency():
    judge = _create_mocked_judge()

    judge._flag_extractor.extract.return_value = None
    judge._confidence_estimator.estimate.return_value = 40
    judge._reason_extractor.extract.return_value = (
        "Reason text"
    )
    judge._next_action_extractor.extract.return_value = [
        "Action 1"
    ]
    judge._hypothesis_extractor.extract.return_value = (
        "Hypothesis 1"
    )
    judge._gemini_prompt_generator.generate.return_value = (
        "Prompt text"
    )

    result = judge.evaluate(
        category="Crypto",
        response="No flag response",
    )

    assert result.flag is None
    assert result.confidence == 40
    assert result.hypothesis == "Hypothesis 1"
    assert result.next_actions == ["Action 1"]
    assert result.gemini_prompt == "Prompt text"


def test_formatter_status_solved_and_confidence():
    formatter = ResultFormatter()

    result = JudgeResult(
        category="Crypto",
        answer="The flag is FLAG{test}",
        flag="FLAG{test}",
        confidence=95,
        reason="Found in text",
        hypothesis=None,
        next_actions=[],
        gemini_prompt=None,
    )

    output = formatter.format(result)

    assert "状態\n================" in output
    assert "解決済み" in output
    assert "信頼度\n================" in output
    assert "95%" in output


def test_formatter_status_unsolved():
    formatter = ResultFormatter()

    result = JudgeResult(
        category="Crypto",
        answer="Analyzing binary...",
        flag=None,
        confidence=30,
        reason="No flag found",
        hypothesis="Try padding oracle",
        next_actions=["Run script"],
        gemini_prompt="Gemini prompt content",
    )

    output = formatter.format(result)

    assert "状態\n================" in output
    assert "未解決" in output
    assert "30%" in output
    assert "Gemini Prompt" not in output


def test_formatter_answer_reason_exact_match_no_duplicate():
    formatter = ResultFormatter()

    result = JudgeResult(
        category="Crypto",
        answer="Exact same response text",
        flag=None,
        confidence=50,
        reason="Exact same response text",
        hypothesis="Some hypothesis",
        next_actions=[],
        gemini_prompt=None,
    )

    output = formatter.format(result)

    assert "AI回答\n================" in output
    assert "根拠\n================" not in output
    assert output.count("Exact same response text") == 1


def test_formatter_confidence_none_shows_unknown():
    formatter = ResultFormatter()

    result = JudgeResult(
        category="Crypto",
        answer="Response text",
        flag=None,
        confidence=None,
        reason="Reason text",
        hypothesis=None,
        next_actions=[],
        gemini_prompt=None,
    )

    output = formatter.format(result)

    assert "信頼度\n================" in output
    assert "不明" in output