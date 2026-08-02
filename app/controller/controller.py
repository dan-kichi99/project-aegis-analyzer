from datetime import datetime, timezone

from app.agents.agent_aggregate_result import AgentAggregateResult
from app.agents.agent_coordinator import AgentCoordinator
from app.agents.agent_input import AgentInput
from app.agents.agent_result import AgentStatus
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
        agent_coordinator: AgentCoordinator | None = None,
    ) -> None:
        self.analyzer = analyzer
        self.knowledge_retriever = knowledge_retriever
        self.prompt_manager = prompt_manager
        self.ai_client = ai_client
        self.judge = judge
        self.context_builder = context_builder or ChallengeContextBuilder()
        self._event_publisher = event_publisher
        self._agent_coordinator = agent_coordinator

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
        category = self.analyzer.analyze(challenge.question)
        knowledge = self.knowledge_retriever.retrieve(category, challenge.question)
        if self._agent_coordinator is not None:
            agent_input = AgentInput(
                challenge=challenge,
                category=category,
                context=context,
                local_knowledge=tuple(knowledge),
                metadata={"file_count": len(challenge.files)},
            )
            aggregate = self._agent_coordinator.analyze(agent_input)
            if self._can_use_agent_result(aggregate):
                return self._agent_judge_result(category, aggregate)

        return self._run_ai_pipeline(
            category=category,
            prompt_input_text=context,
            knowledge=knowledge,
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

        return self._run_ai_pipeline(category, prompt_input_text, knowledge)

    def _run_ai_pipeline(
        self,
        category: str,
        prompt_input_text: str,
        knowledge: list[str],
    ) -> JudgeResult:
        # AI用Prompt生成
        prompt = self.prompt_manager.build(
            question=prompt_input_text,
            category=category,
            knowledge=knowledge,
        )

        # AI生成
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

        # Judge
        return self.judge.evaluate(
            category,
            ai_response,
        )

    def _can_use_agent_result(self, aggregate: AgentAggregateResult) -> bool:
        if aggregate.status is AgentStatus.COMPLETED:
            return True
        if aggregate.status is AgentStatus.SKIPPED:
            return False
        return any(
            result.answer is not None or result.flag_candidate is not None
            for result in aggregate.results
        )

    def _agent_judge_result(
        self,
        category: str,
        aggregate: AgentAggregateResult,
    ) -> JudgeResult:
        primary = aggregate.primary_result
        answer = primary.answer if primary is not None else None
        return JudgeResult(
            category=category,
            answer=answer or aggregate.summary,
            flag=None,
            confidence=aggregate.confidence,
            reason="専門Agentによる解析結果です。Flag候補は未確定です。",
            hypothesis=aggregate.summary,
            next_actions=list(aggregate.next_actions),
            gemini_prompt=None,
            agent_result=aggregate,
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
