from unittest.mock import MagicMock, patch

import pytest
from openai import OpenAIError

from app.main import main


def configure_cli_mocks(
    config_cls: MagicMock,
    service_cls: MagicMock,
    error: Exception,
) -> None:
    config_cls.return_value.openai_api_key = "test-key"
    config_cls.return_value.openai_model = "gpt-4o-mini"
    service_cls.return_value.solve.side_effect = error


@patch("app.main.Config")
@patch("app.main.OpenAIClient")
@patch("app.main.ChallengeService")
@patch("builtins.input", side_effect=["問題文", ""])
@patch("builtins.print")
def test_runtime_error_displays_japanese_message_and_exits_with_code_one(
    print_mock: MagicMock,
    input_mock: MagicMock,
    service_cls: MagicMock,
    openai_client: MagicMock,
    config_cls: MagicMock,
):
    configure_cli_mocks(
        config_cls,
        service_cls,
        RuntimeError("OpenAI API returned an empty response."),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    print_mock.assert_any_call(
        "AIとの通信中にエラーが発生しました。\n"
        "詳細：OpenAI API returned an empty response."
    )


@patch("app.main.Config")
@patch("app.main.OpenAIClient")
@patch("app.main.ChallengeService")
@patch("builtins.input", side_effect=["問題文", "missing.txt"])
@patch("builtins.print")
def test_existing_file_not_found_error_handling_is_preserved(
    print_mock: MagicMock,
    input_mock: MagicMock,
    service_cls: MagicMock,
    openai_client: MagicMock,
    config_cls: MagicMock,
):
    configure_cli_mocks(
        config_cls,
        service_cls,
        FileNotFoundError("File not found: missing.txt"),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    print_mock.assert_any_call("エラー：File not found: missing.txt")


@patch("app.main.Config")
@patch("app.main.OpenAIClient")
@patch("app.main.ChallengeService")
@patch("builtins.input", side_effect=["問題文", ""])
@patch("builtins.print")
def test_openai_sdk_error_displays_japanese_message_and_exits_with_code_one(
    print_mock: MagicMock,
    input_mock: MagicMock,
    service_cls: MagicMock,
    openai_client: MagicMock,
    config_cls: MagicMock,
):
    """AI経路で発生したOpenAI SDKのOpenAIErrorがCLIから漏れず、
    RuntimeErrorと同じGraceful Failureになることを固定する回帰テスト。
    """
    configure_cli_mocks(
        config_cls,
        service_cls,
        OpenAIError("Connection error."),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    print_mock.assert_any_call(
        "AIとの通信中にエラーが発生しました。\n詳細：Connection error."
    )


@patch("app.main.OpenAIClient")
@patch("app.main.ChallengeService")
@patch("builtins.input")
@patch("builtins.print")
def test_missing_api_key_displays_japanese_message_and_exits_with_code_one(
    print_mock: MagicMock,
    input_mock: MagicMock,
    service_cls: MagicMock,
    openai_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
):
    """OPENAI_API_KEY未設定時にCLIが未捕捉Exceptionで終了せず、
    Graceful FailureになることをConfigを実物のまま固定する回帰テスト。
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    print_mock.assert_any_call("エラー：OPENAI_API_KEYが設定されていません。")
    input_mock.assert_not_called()
    service_cls.return_value.solve.assert_not_called()
