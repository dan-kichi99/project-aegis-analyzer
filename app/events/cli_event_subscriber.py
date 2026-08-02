from typing import ClassVar

from app.events.analysis_event import AnalysisEvent, AnalysisEventType


class CliEventSubscriber:
    """解析イベントを日本語CLIメッセージとして表示する。"""

    _MESSAGES: ClassVar[dict[AnalysisEventType, str]] = {
        AnalysisEventType.LOCAL_SOLUTION_FOUND: "ローカル解析でFlag候補を検出しました。",
        AnalysisEventType.AI_ANALYSIS_STARTED: (
            "ローカル解析では解決できなかったため、AI解析を開始します。"
        ),
        AnalysisEventType.AI_ANALYSIS_COMPLETED: "AI解析が完了しました。",
        AnalysisEventType.ANALYSIS_COMPLETED: "解析が完了しました。",
        AnalysisEventType.ANALYSIS_FAILED: "解析中にエラーが発生しました。",
    }

    def __call__(self, event: AnalysisEvent) -> None:
        if event.event_type is AnalysisEventType.ANALYSIS_STARTED:
            print(
                "========================\n"
                "Project Aegis\n"
                "解析中...\n"
                "========================",
                flush=True,
            )
            return
        message = self._MESSAGES.get(event.event_type)
        if message is not None:
            print(message)
