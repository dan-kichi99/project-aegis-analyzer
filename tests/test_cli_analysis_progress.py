from datetime import datetime, timezone
from unittest.mock import call, patch

import pytest

from app.judge.judge_result import JudgeResult
from app.main import main

ANALYSIS_MESSAGE = (
    "========================\n"
    "Project Aegis\n"
    "解析中...\n"
    "========================"
)


@pytest.fixture
def cli_mocks():
    with (
        patch("app.main.Config") as config_cls,
        patch("app.main.OpenAIClient"),
        patch("app.main.ChallengeService") as service_cls,
        patch("builtins.input", side_effect=["問題文", "sample.txt"]),
        patch("builtins.print") as print_mock,
    ):
        config_cls.return_value.openai_api_key = "test-key"
        config_cls.return_value.openai_model = "gpt-4o-mini"
        result = JudgeResult(
            category="Web",
            answer="解析結果",
            flag=None,
            confidence=80,
            reason=None,
            hypothesis=None,
            next_actions=[],
            gemini_prompt=None,
        )
        service_cls.return_value.solve.return_value = result

        def solve_with_event(**kwargs):
            publisher = service_cls.call_args.kwargs["event_publisher"]
            publisher.publish(
                AnalysisEvent(
                    event_type=AnalysisEventType.ANALYSIS_STARTED,
                    message="解析を開始しました。",
                    phase="input",
                    timestamp=datetime.now(timezone.utc),
                    metadata={"file_count": 1},
                )
            )
            return result

        service_cls.return_value.solve.side_effect = solve_with_event
        yield service_cls.return_value, print_mock


def test_main_displays_analysis_start_message(cli_mocks):
    _, print_mock = cli_mocks

    main()

    assert call(ANALYSIS_MESSAGE, flush=True) in print_mock.call_args_list


def test_analysis_message_is_displayed_before_service_returns(cli_mocks):
    service, print_mock = cli_mocks
    solve_with_event = service.solve.side_effect

    def verify_progress_is_visible(**kwargs):
        result = solve_with_event(**kwargs)
        assert call(ANALYSIS_MESSAGE, flush=True) in print_mock.call_args_list
        return result

    service.solve.side_effect = verify_progress_is_visible

    main()


def test_existing_cli_processing_and_result_display_are_preserved(cli_mocks):
    service, print_mock = cli_mocks

    main()

    service.solve.assert_called_once_with(
        question="問題文",
        file_paths=["sample.txt"],
    )
    result_call = next(
        printed_call
        for printed_call in print_mock.call_args_list
        if printed_call.args
        and "Project Aegis 解析結果" in str(printed_call.args[0])
    )
    assert print_mock.call_args_list.index(
        call(ANALYSIS_MESSAGE, flush=True)
    ) < print_mock.call_args_list.index(result_call)
from app.events.analysis_event import AnalysisEvent, AnalysisEventType
