from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.iteration.iteration_action import IterationAction
from app.iteration.iteration_state import (
    HypothesisStatus,
    IterationSession,
)
from app.iteration.local_analysis_result import (
    LocalAnalysisResult,
    LocalAnalysisStatus,
)


@dataclass(slots=True, frozen=True)
class LocalAnalysisRequest:
    session: IterationSession
    action: IterationAction


class BaseLocalAnalysisExecutor(ABC):
    @property
    @abstractmethod
    def analysis_type(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def execute(self, request: LocalAnalysisRequest) -> LocalAnalysisResult:
        raise NotImplementedError


class HypothesisReviewExecutor(BaseLocalAnalysisExecutor):
    @property
    def analysis_type(self) -> str:
        return "hypothesis_review"

    def execute(self, request: LocalAnalysisRequest) -> LocalAnalysisResult:
        hypothesis_id = request.action.metadata.get("hypothesis_id")
        if not isinstance(hypothesis_id, str) or not hypothesis_id.strip():
            return self._result(
                request,
                LocalAnalysisStatus.FAILED,
                "対象仮説IDが指定されていません。",
                (),
                "hypothesis_idが見つかりません。",
            )
        hypothesis = next(
            (
                item
                for item in request.session.hypotheses
                if item.hypothesis_id == hypothesis_id
            ),
            None,
        )
        if hypothesis is None:
            return self._result(
                request,
                LocalAnalysisStatus.FAILED,
                "対象仮説が見つかりませんでした。",
                (),
                "指定されたhypothesis_idはSessionに存在しません。",
            )
        if hypothesis.status in {HypothesisStatus.REJECTED, HypothesisStatus.RESOLVED}:
            return self._result(
                request,
                LocalAnalysisStatus.SKIPPED,
                "対象仮説は既に終了状態のため整理をスキップしました。",
                (),
                None,
            )
        summary = (
            f"仮説「{hypothesis_id[:400]}」の既存根拠を反復解析用に整理しました。"
        )[:500]
        return self._result(
            request,
            LocalAnalysisStatus.COMPLETED,
            summary,
            (hypothesis,),
            None,
        )

    def _result(
        self,
        request: LocalAnalysisRequest,
        status: LocalAnalysisStatus,
        summary: str,
        hypotheses: tuple,
        error_message: str | None,
    ) -> LocalAnalysisResult:
        return LocalAnalysisResult(
            action_id=request.action.action_id,
            analysis_type=self.analysis_type,
            status=status,
            summary=summary,
            hypotheses=hypotheses,
            open_questions=(),
            flag_candidates=(),
            next_actions=(),
            error_message=error_message,
        )
