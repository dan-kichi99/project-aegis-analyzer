from unittest.mock import MagicMock, patch

import pytest

from app.config import Config
from app.judge.judge_result import JudgeResult
from app.main import main
from app.utils.result_formatter import ResultFormatter


def make_result(**overrides: object) -> JudgeResult:
    values = {
        "category": "Web",
        "answer": "テスト回答",
        "flag": None,
        "confidence": 80,
        "reason": None,
        "hypothesis": None,
        "next_actions": [],
        "gemini_prompt": None,
    }
    values.update(overrides)
    return JudgeResult(**values)  # type: ignore[arg-type]


def test_result_formatter_displays_japanese_headings():
    output = ResultFormatter().format(make_result())

    for heading in ("カテゴリ", "状態", "信頼度", "AI回答"):
        assert heading in output


def test_result_formatter_displays_solved_status_and_flag_heading():
    output = ResultFormatter().format(make_result(flag="flag{test}"))

    assert "解決済み" in output
    assert "Flag候補" in output


def test_result_formatter_displays_unsolved_status_without_flag():
    output = ResultFormatter().format(make_result(flag=None))

    assert "未解決" in output


def test_result_formatter_translates_crypto_category():
    output = ResultFormatter().format(make_result(category="Crypto"))

    assert "暗号" in output


def test_result_formatter_displays_unknown_when_confidence_is_none():
    output = ResultFormatter().format(make_result(confidence=None))

    assert "不明" in output


def test_result_formatter_does_not_display_legacy_english_headings():
    output = ResultFormatter().format(
        make_result(next_actions=["追加調査を行う"])
    )

    for heading in (
        "Category",
        "Status",
        "Confidence",
        "Answer",
        "Next Actions",
    ):
        assert heading not in output


@patch("app.main.Config")
@patch("app.main.OpenAIClient")
@patch("app.main.ChallengeService")
def test_main_displays_japanese_input_prompts(
    mock_service_cls: MagicMock,
    mock_openai_client: MagicMock,
    mock_config_cls: MagicMock,
    capsys: pytest.CaptureFixture[str],
):
    mock_config_cls.return_value.openai_api_key = "test-key"
    mock_config_cls.return_value.openai_model = "gpt-4o-mini"
    mock_service_cls.return_value.solve.return_value = make_result()

    with patch("builtins.input", side_effect=["問題文", ""]):
        main()

    output = capsys.readouterr().out
    assert "問題文を入力してください：" in output
    assert "添付ファイルのパスをカンマ区切りで入力してください。" in output
    mock_openai_client.assert_called_once()
    mock_service_cls.return_value.solve.assert_called_once_with(
        question="問題文",
        file_paths=[],
    )


@patch("app.main.Config")
@patch("app.main.OpenAIClient")
@patch("app.main.ChallengeService")
def test_main_displays_japanese_file_not_found_error_prefix(
    mock_service_cls: MagicMock,
    mock_openai_client: MagicMock,
    mock_config_cls: MagicMock,
    capsys: pytest.CaptureFixture[str],
):
    mock_config_cls.return_value.openai_api_key = "test-key"
    mock_config_cls.return_value.openai_model = "gpt-4o-mini"
    mock_service_cls.return_value.solve.side_effect = FileNotFoundError(
        "missing.txt"
    )

    with (
        patch("builtins.input", side_effect=["問題文", "missing.txt"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()

    assert exc_info.value.code == 1
    assert "エラー：" in capsys.readouterr().out
    mock_openai_client.assert_called_once()


def test_config_missing_api_key_error_is_japanese(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(
        ValueError,
        match="OPENAI_API_KEYが設定されていません。",
    ):
        Config()
