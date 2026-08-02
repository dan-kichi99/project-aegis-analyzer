from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.analyzer.analyzer import Analyzer
from app.challenge.challenge_service import ChallengeService
from app.client.base_client import BaseAIClient
from app.controller.controller import Controller
from app.events.analysis_event import AnalysisEvent, AnalysisEventType
from app.events.cli_event_subscriber import CliEventSubscriber
from app.events.event_publisher import EventPublisher
from app.file.file_loader import FileLoader
from app.file.static_file_analyzer import StaticFileAnalyzer
from app.judge.judge_result import JudgeResult
from app.main import main
from app.prompt.prompt_manager import PromptManager


class RecordingFakeAIClient(BaseAIClient):
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "AI解析結果"


def _build_service(
    publisher: EventPublisher | None,
) -> tuple[ChallengeService, RecordingFakeAIClient]:
    analyzer = Analyzer()
    ai_client = RecordingFakeAIClient()
    knowledge = MagicMock()
    knowledge.retrieve.return_value = []
    judge = MagicMock()
    judge.evaluate.side_effect = lambda category, answer: JudgeResult(
        category=category,
        answer=answer,
        flag=None,
        confidence=50,
        reason="AI解析",
        hypothesis=None,
        next_actions=[],
        gemini_prompt=None,
    )
    controller = Controller(
        analyzer=analyzer,
        knowledge_retriever=knowledge,
        prompt_manager=PromptManager(),
        ai_client=ai_client,
        judge=judge,
        event_publisher=publisher,
    )
    return (
        ChallengeService(
            controller=controller,
            analyzer=analyzer,
            file_loader=FileLoader(),
            file_analyzer=StaticFileAnalyzer(),
            event_publisher=publisher,
        ),
        ai_client,
    )


def _types(events: list[AnalysisEvent]) -> list[AnalysisEventType]:
    return [event.event_type for event in events]


def test_local_solution_event_order_and_metadata(tmp_path: Path):
    path = tmp_path / "flag.txt"
    path.write_text("FLAG{event_local}", encoding="utf-8")
    publisher = EventPublisher()
    events: list[AnalysisEvent] = []
    publisher.subscribe(events.append)
    service, ai_client = _build_service(publisher)

    result = service.solve("Analyze", [path])

    assert result.flag == "FLAG{event_local}"
    assert ai_client.prompts == []
    assert _types(events) == [
        AnalysisEventType.ANALYSIS_STARTED,
        AnalysisEventType.LOCAL_SOLUTION_FOUND,
        AnalysisEventType.ANALYSIS_COMPLETED,
    ]
    assert events[0].metadata == {"file_count": 1}
    assert events[1].metadata == {"category": "Unknown", "method": "direct_flag"}
    assert events[2].metadata == {"solved": True, "category": "Unknown"}


def test_ai_path_event_order_and_single_counts():
    publisher = EventPublisher()
    events: list[AnalysisEvent] = []
    publisher.subscribe(events.append)
    service, ai_client = _build_service(publisher)

    result = service.solve("ordinary challenge")

    assert result.flag is None
    assert len(ai_client.prompts) == 1
    assert _types(events) == [
        AnalysisEventType.ANALYSIS_STARTED,
        AnalysisEventType.AI_ANALYSIS_STARTED,
        AnalysisEventType.AI_ANALYSIS_COMPLETED,
        AnalysisEventType.ANALYSIS_COMPLETED,
    ]
    assert _types(events).count(AnalysisEventType.ANALYSIS_COMPLETED) == 1
    assert _types(events).count(AnalysisEventType.AI_ANALYSIS_STARTED) == 1
    assert _types(events).count(AnalysisEventType.AI_ANALYSIS_COMPLETED) == 1


def test_local_method_identifiers_cover_solver_types():
    publisher = EventPublisher()
    event = AnalysisEvent(
        event_type=AnalysisEventType.LOCAL_SOLUTION_FOUND,
        message="ローカル解析でFlag候補を検出しました。",
        phase="local_solver",
        timestamp=MagicMock(),
        metadata={"category": "Crypto", "method": "single_byte_xor"},
    )

    publisher.publish(event)

    assert event.metadata["method"] in {
        "direct_flag",
        "single_byte_xor",
        "caesar",
        "rsa",
        "appended_data",
    }


def test_subscriber_failure_does_not_stop_analysis(tmp_path: Path):
    path = tmp_path / "flag.txt"
    path.write_text("FLAG{subscriber_failure}", encoding="utf-8")
    publisher = EventPublisher()

    def failing_subscriber(event: AnalysisEvent) -> None:
        raise RuntimeError("subscriber failed")

    publisher.subscribe(failing_subscriber)
    service, _ = _build_service(publisher)

    result = service.solve("Analyze", [path])

    assert result.flag == "FLAG{subscriber_failure}"


def test_publisher_none_preserves_service_and_controller_behavior():
    service, ai_client = _build_service(None)

    result = service.solve("ordinary challenge")

    assert result.flag is None
    assert len(ai_client.prompts) == 1


def test_event_metadata_contains_no_secrets_or_payloads(tmp_path: Path):
    path = tmp_path / "flag.txt"
    path.write_text("FLAG{must_not_enter_metadata}", encoding="utf-8")
    publisher = EventPublisher()
    events: list[AnalysisEvent] = []
    publisher.subscribe(events.append)
    service, _ = _build_service(publisher)

    service.solve("Analyze", [path])

    serialized = repr([dict(event.metadata) for event in events])
    assert "FLAG{must_not_enter_metadata}" not in serialized
    assert "api_key" not in serialized.casefold()
    assert "prompt" not in serialized.casefold()


def test_cli_subscriber_displays_messages_without_exiting(capsys):
    subscriber = CliEventSubscriber()
    publisher = EventPublisher()
    publisher.subscribe(subscriber)
    for event_type in (
        AnalysisEventType.ANALYSIS_STARTED,
        AnalysisEventType.LOCAL_SOLUTION_FOUND,
        AnalysisEventType.AI_ANALYSIS_STARTED,
        AnalysisEventType.AI_ANALYSIS_COMPLETED,
        AnalysisEventType.ANALYSIS_COMPLETED,
        AnalysisEventType.ANALYSIS_FAILED,
    ):
        publisher.publish(
            AnalysisEvent(
                event_type=event_type,
                message="message",
                phase="test",
                timestamp=MagicMock(),
                metadata={},
            )
        )

    output = capsys.readouterr().out
    assert "Project Aegis" in output
    assert "ローカル解析でFlag候補を検出しました。" in output
    assert "AI解析を開始します。" in output
    assert "AI解析が完了しました。" in output
    assert "解析が完了しました。" in output
    assert "解析中にエラーが発生しました。" in output


def test_main_creates_subscriber_and_shares_publisher():
    publisher = EventPublisher()
    dummy_result = JudgeResult(category="Misc", answer="done")
    with (
        patch("app.main.EventPublisher", return_value=publisher) as publisher_cls,
        patch("app.main.CliEventSubscriber") as subscriber_cls,
        patch("app.main.Config") as config_cls,
        patch("app.main.OpenAIClient"),
        patch("app.main.Controller") as controller_cls,
        patch("app.main.ChallengeService") as service_cls,
        patch("builtins.input", side_effect=["question", ""]),
        patch("builtins.print"),
    ):
        config_cls.return_value.openai_api_key = "test-key"
        config_cls.return_value.openai_model = "test-model"
        service_cls.return_value.solve.return_value = dummy_result

        main()

    publisher_cls.assert_called_once_with()
    subscriber_cls.assert_called_once_with()
    assert subscriber_cls.return_value in publisher._subscribers
    assert controller_cls.call_args.kwargs["event_publisher"] is publisher
    assert service_cls.call_args.kwargs["event_publisher"] is publisher


@pytest.mark.parametrize(
    ("error", "expected_text"),
    [
        (RuntimeError("api failed"), "AIとの通信中にエラーが発生しました。"),
        (FileNotFoundError("missing"), "エラー：missing"),
        (ValueError("invalid"), "エラー：invalid"),
    ],
)
def test_main_publishes_single_failed_event_and_preserves_error_display(
    error,
    expected_text,
):
    publisher = EventPublisher()
    events: list[AnalysisEvent] = []
    publisher.subscribe(events.append)
    with (
        patch("app.main.EventPublisher", return_value=publisher),
        patch("app.main.Config") as config_cls,
        patch("app.main.OpenAIClient"),
        patch("app.main.ChallengeService") as service_cls,
        patch("builtins.input", side_effect=["question", ""]),
        patch("builtins.print") as print_mock,
        pytest.raises(SystemExit) as exit_info,
    ):
        config_cls.return_value.openai_api_key = "test-key"
        config_cls.return_value.openai_model = "test-model"
        service_cls.return_value.solve.side_effect = error
        main()

    assert exit_info.value.code == 1
    assert _types(events).count(AnalysisEventType.ANALYSIS_FAILED) == 1
    assert events[-1].metadata == {"error_type": type(error).__name__}
    assert any(expected_text in str(call.args[0]) for call in print_mock.call_args_list)
