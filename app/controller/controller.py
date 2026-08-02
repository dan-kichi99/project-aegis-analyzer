from datetime import datetime, timezone

from app.analyzer.analyzer import Analyzer
from app.challenge.challenge_context_builder import ChallengeContextBuilder
from app.challenge.challenge_input import ChallengeInput
from app.client.base_client import BaseAIClient
from app.events.analysis_event import AnalysisEvent, AnalysisEventType
from app.events.event_publisher import EventPublisher
from app.judge.judge import Judge
from app.judge.judge_result import JudgeResult
from app.knowledge.knowledge_retriever import KnowledgeRetriever
from app.prompt.prompt_manager import PromptManager


class Controller:
    """CTF解析パイプライン全体を統括するコントローラー。"""

    def __init__(
        self,
        analyzer: Analyzer,
        knowledge_retriever: KnowledgeRetriever,
        prompt_manager: PromptManager,
        ai_client: BaseAIClient,
        judge: Judge,
        context_builder: ChallengeContextBuilder | None = None,
        event_publisher: EventPublisher | None = None,
    ) -> None:
        self.analyzer = analyzer
        self.knowledge_retriever = knowledge_retriever
        self.prompt_manager = prompt_manager
        self.ai_client = ai_client
        self.judge = judge
        self.context_builder = context_builder or ChallengeContextBuilder()
        self._event_publisher = event_publisher

    def process(self, question: str) -> JudgeResult:
        """問題文のみを受け取って解析する後方互換メソッド。"""
        return self._run_pipeline(
            analysis_target_text=question,
            retrieval_target_text=question,
            prompt_input_text=question,
        )

    def process_challenge(
        self,
        challenge: ChallengeInput,
    ) -> JudgeResult:
        """問題文と添付ファイル解析結果をまとめて解析する。"""
        context = self.context_builder.build(challenge)

        return self._run_pipeline(
            analysis_target_text=challenge.question,
            retrieval_target_text=challenge.question,
            prompt_input_text=context,
        )

    def _run_pipeline(
        self,
        analysis_target_text: str,
        retrieval_target_text: str,
        prompt_input_text: str,
    ) -> JudgeResult:
        """共通解析パイプラインを実行する。"""

        # 1. 問題文からカテゴリ判定
        category = self.analyzer.analyze(
            analysis_target_text
        )

        # 2. 問題文を基準にローカルKnowledge検索
        knowledge = self.knowledge_retriever.retrieve(
            category,
            retrieval_target_text,
        )

        # 3. AI用Prompt生成
        prompt = self.prompt_manager.build(
            question=prompt_input_text,
            category=category,
            knowledge=knowledge,
        )

        # 4. AI生成
        self._publish(
            AnalysisEventType.AI_ANALYSIS_STARTED,
            "AI解析を開始します。",
            "ai",
            {"category": category},
        )
        ai_response = self.ai_client.generate(
            prompt
        )
        self._publish(
            AnalysisEventType.AI_ANALYSIS_COMPLETED,
            "AI解析が完了しました。",
            "ai",
            {"category": category},
        )

        # 5. Judge
        return self.judge.evaluate(
            category,
            ai_response,
        )

    def _publish(
        self,
        event_type: AnalysisEventType,
        message: str,
        phase: str,
        metadata: dict[str, object],
    ) -> None:
        if self._event_publisher is None:
            return
        self._event_publisher.publish(
            AnalysisEvent(
                event_type=event_type,
                message=message,
                phase=phase,
                timestamp=datetime.now(timezone.utc),
                metadata=metadata,
            )
        )
