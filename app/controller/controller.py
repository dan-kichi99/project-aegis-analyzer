from collections.abc import Callable
from datetime import datetime, timezone

from app.agents.agent_aggregate_result import AgentAggregateResult
from app.agents.agent_coordinator import AgentCoordinator
from app.agents.agent_input import AgentInput
from app.agents.agent_result import AgentStatus, AgentType
from app.analyzer.analyzer import Analyzer
from app.challenge.challenge_context_builder import ChallengeContextBuilder
from app.challenge.challenge_input import ChallengeInput
from app.client.base_client import BaseAIClient
from app.events.analysis_event import AnalysisEvent, AnalysisEventType
from app.events.event_publisher import EventPublisher
from app.judge.judge import Judge
from app.judge.judge_result import JudgeResult
from app.knowledge.knowledge_retriever import KnowledgeRetriever
from app.optimization.ai_usage_result import (
    AiCallSource,
    ChallengeExecutionResult,
)
from app.optimization.ai_usage_tracker import AiUsageTracker
from app.optimization.challenge_ai_session import (
    ChallengeAiSession,
    SourceBoundAIClient,
)
from app.prompt.prompt_manager import PromptManager

DEFAULT_MAX_AI_CALLS_PER_CHALLENGE = 3


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
        max_ai_calls_per_challenge: int = DEFAULT_MAX_AI_CALLS_PER_CHALLENGE,
    ) -> None:
        if (
            isinstance(max_ai_calls_per_challenge, bool)
            or not isinstance(max_ai_calls_per_challenge, int)
            or max_ai_calls_per_challenge < 0
        ):
            raise ValueError(
                "max_ai_calls_per_challenge must be a non-negative integer."
            )
        self.analyzer = analyzer
        self.knowledge_retriever = knowledge_retriever
        self.prompt_manager = prompt_manager
        self.ai_client = ai_client
        self.judge = judge
        self.context_builder = context_builder or ChallengeContextBuilder()
        self._event_publisher = event_publisher
        self._agent_coordinator = agent_coordinator
        self._max_ai_calls_per_challenge = max_ai_calls_per_challenge

    def process(self, question: str) -> JudgeResult:
        """問題文のみを受け取って解析する後方互換メソッド。"""
        return self.process_with_usage(question).result

    def process_with_usage(
        self,
        question: str,
        *,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> ChallengeExecutionResult:
        tracker, session = self._new_ai_session(cancel_requested)
        context = self.context_builder.build(ChallengeInput(question=question, files=[]))
        result = self._run_pipeline(
            analysis_target_text=question,
            retrieval_target_text=question,
            prompt_input_text=question,
            ai_client=SourceBoundAIClient(
                session=session,
                source=AiCallSource.CONTROLLER_FALLBACK,
            ),
        )
        return ChallengeExecutionResult(
            result=result,
            analysis_context=context,
            ai_usage=tracker.snapshot(
                knowledge_retrieval_count=1,
                agent_run_count=0,
                local_solution_avoided_ai=False,
            ),
        )

    def process_challenge(
        self,
        challenge: ChallengeInput,
    ) -> JudgeResult:
        """問題文と添付ファイル解析結果をまとめて解析する。"""
        return self.process_challenge_with_usage(challenge).result

    def process_challenge_with_usage(
        self,
        challenge: ChallengeInput,
        *,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> ChallengeExecutionResult:
        tracker, session = self._new_ai_session(cancel_requested)
        fallback_client = SourceBoundAIClient(
            session=session,
            source=AiCallSource.CONTROLLER_FALLBACK,
        )
        context = self.context_builder.build(challenge)
        category = self.analyzer.analyze(challenge.question)
        knowledge = self.knowledge_retriever.retrieve(category, challenge.question)
        agent_runs = 0
        coordinator = self._challenge_coordinator(session)
        if coordinator is not None:
            agent_input = AgentInput(
                challenge=challenge,
                category=category,
                context=context,
                local_knowledge=tuple(knowledge),
                metadata={"file_count": len(challenge.files)},
            )
            aggregate = coordinator.analyze(agent_input)
            agent_runs = len(aggregate.results)
            if self._can_use_agent_result(aggregate):
                result = self._agent_judge_result(category, aggregate)
                return ChallengeExecutionResult(
                    result=result,
                    analysis_context=context,
                    ai_usage=tracker.snapshot(
                        knowledge_retrieval_count=1,
                        agent_run_count=agent_runs,
                        local_solution_avoided_ai=(
                            tracker.executed_calls == 0
                        ),
                    ),
                )

        result = self._run_ai_pipeline(
            category=category,
            prompt_input_text=context,
            knowledge=knowledge,
            ai_client=fallback_client,
        )
        return ChallengeExecutionResult(
            result=result,
            analysis_context=context,
            ai_usage=tracker.snapshot(
                knowledge_retrieval_count=1,
                agent_run_count=agent_runs,
                local_solution_avoided_ai=False,
            ),
        )

    def _run_pipeline(
        self,
        analysis_target_text: str,
        retrieval_target_text: str,
        prompt_input_text: str,
        ai_client: BaseAIClient | None = None,
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

        return self._run_ai_pipeline(
            category, prompt_input_text, knowledge, ai_client=ai_client
        )

    def _run_ai_pipeline(
        self,
        category: str,
        prompt_input_text: str,
        knowledge: list[str],
        ai_client: BaseAIClient | None = None,
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
        ai_response = (ai_client or self.ai_client).generate(
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

    def _new_ai_session(
        self,
        cancel_requested: Callable[[], bool] | None,
    ) -> tuple[AiUsageTracker, ChallengeAiSession]:
        tracker = AiUsageTracker()
        return tracker, ChallengeAiSession(
            client=self.ai_client,
            tracker=tracker,
            max_ai_calls=self._max_ai_calls_per_challenge,
            cancel_requested=cancel_requested,
        )

    def _challenge_coordinator(
        self,
        session: ChallengeAiSession,
    ) -> AgentCoordinator | None:
        if self._agent_coordinator is None:
            return None
        return self._agent_coordinator.with_ai_clients(
            {
                AgentType.CRYPTO: SourceBoundAIClient(
                    session=session, source=AiCallSource.CRYPTO_AGENT
                ),
                AgentType.REV: SourceBoundAIClient(
                    session=session, source=AiCallSource.REV_AGENT
                ),
                AgentType.WEB: SourceBoundAIClient(
                    session=session, source=AiCallSource.WEB_AGENT
                ),
                AgentType.FORENSICS: SourceBoundAIClient(
                    session=session, source=AiCallSource.FORENSICS_AGENT
                ),
            }
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
