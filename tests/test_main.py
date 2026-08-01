from unittest.mock import MagicMock, patch

import pytest

from app.judge.judge_result import JudgeResult
from app.main import main, parse_file_paths


def test_parse_file_paths_empty():
    assert parse_file_paths("") == []
    assert parse_file_paths("   ") == []


def test_parse_file_paths_single():
    assert parse_file_paths(r"C:\CTF\challenge.exe") == [
        r"C:\CTF\challenge.exe"
    ]


def test_parse_file_paths_multiple_with_whitespace():
    raw = r" C:\CTF\a.exe ,  C:\CTF\b.txt , "
    expected = [
        r"C:\CTF\a.exe",
        r"C:\CTF\b.txt",
    ]

    assert parse_file_paths(raw) == expected


@patch("app.main.Config")
@patch("app.main.ChallengeService")
@patch("app.main.OpenAIClient")
@patch("builtins.input")
@patch("builtins.print")
def test_main_cli_question_only(
    mock_print: MagicMock,
    mock_input: MagicMock,
    mock_openai_client: MagicMock,
    mock_service_cls: MagicMock,
    mock_config_cls: MagicMock,
):
    mock_config = MagicMock()
    mock_config.openai_api_key = "test-key"
    mock_config.openai_model = "gpt-4o-mini"
    mock_config_cls.return_value = mock_config

    mock_input.side_effect = [
        "Decrypt this RSA challenge.",
        "",
    ]

    mock_service = MagicMock()
    mock_service_cls.return_value = mock_service

    dummy_result = JudgeResult(
        category="crypto",
        answer="FLAG{cli_q_only}",
        flag="FLAG{cli_q_only}",
        confidence=100,
        reason="Found flag in RSA key",
        hypothesis=None,
        next_actions=[],
        gemini_prompt=None,
    )

    mock_service.solve.return_value = dummy_result

    main()

    mock_service.solve.assert_called_once_with(
        question="Decrypt this RSA challenge.",
        file_paths=[],
    )


@patch("app.main.Config")
@patch("app.main.ChallengeService")
@patch("app.main.OpenAIClient")
@patch("builtins.input")
@patch("builtins.print")
def test_main_cli_single_file_integration(
    mock_print: MagicMock,
    mock_input: MagicMock,
    mock_openai_client: MagicMock,
    mock_service_cls: MagicMock,
    mock_config_cls: MagicMock,
):
    mock_config = MagicMock()
    mock_config.openai_api_key = "test-key"
    mock_config.openai_model = "gpt-4o-mini"
    mock_config_cls.return_value = mock_config

    mock_input.side_effect = [
        "Find the flag in attached file.",
        r"challenge.txt",
    ]

    mock_service = MagicMock()
    mock_service_cls.return_value = mock_service

    dummy_result = JudgeResult(
        category="general",
        answer="FLAG{aegis_real_smoke_test}",
        flag="FLAG{aegis_real_smoke_test}",
        confidence=100,
        reason="Found in text file",
        hypothesis=None,
        next_actions=[],
        gemini_prompt=None,
    )

    mock_service.solve.return_value = dummy_result

    main()

    mock_service.solve.assert_called_once_with(
        question="Find the flag in attached file.",
        file_paths=[r"challenge.txt"],
    )


@patch("app.main.Config")
@patch("app.main.ChallengeService")
@patch("app.main.OpenAIClient")
@patch("builtins.input")
@patch("builtins.print")
def test_main_cli_file_not_found_error_handling(
    mock_print: MagicMock,
    mock_input: MagicMock,
    mock_openai_client: MagicMock,
    mock_service_cls: MagicMock,
    mock_config_cls: MagicMock,
):
    mock_config = MagicMock()
    mock_config.openai_api_key = "test-key"
    mock_config.openai_model = "gpt-4o-mini"
    mock_config_cls.return_value = mock_config

    mock_input.side_effect = [
        "Read file",
        r"nonexistent.txt",
    ]

    mock_service = MagicMock()
    mock_service_cls.return_value = mock_service

    mock_service.solve.side_effect = FileNotFoundError(
        "File not found: nonexistent.txt"
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    mock_print.assert_any_call(
        "Error: File not found: nonexistent.txt"
    )


@patch("app.main.Config")
@patch("app.main.OpenAIClient")
@patch("app.main.ChallengeService")
@patch("builtins.input")
@patch("builtins.print")
def test_api_key_not_printed(
    mock_print: MagicMock,
    mock_input: MagicMock,
    mock_service_cls: MagicMock,
    mock_openai_client: MagicMock,
    mock_config_cls: MagicMock,
):
    mock_config = MagicMock()
    mock_config.openai_api_key = "secret_sk_live_12345"
    mock_config.openai_model = "gpt-4o-mini"
    mock_config_cls.return_value = mock_config

    mock_input.side_effect = [
        "Question text",
        "",
    ]

    mock_service = MagicMock()
    mock_service_cls.return_value = mock_service

    mock_service.solve.return_value = JudgeResult(
        category="crypto",
        answer="FLAG{test}",
        flag="FLAG{test}",
        confidence=100,
        reason="ok",
        hypothesis=None,
        next_actions=[],
        gemini_prompt=None,
    )

    main()

    for call_args in mock_print.call_args_list:
        args, _ = call_args

        for arg in args:
            assert "secret_sk_live_12345" not in str(arg)