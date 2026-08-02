from app.agents.agent_aggregate_result import AgentAggregateResult, AgentConflict
from app.agents.agent_plan import AgentExecutionPlan
from app.agents.agent_result import AgentEvidence, AgentResult, AgentStatus, AgentType

MAX_AGGREGATE_EVIDENCE = 30
MAX_AGGREGATE_EVIDENCE_DETAIL_CHARACTERS = 500
MAX_AGGREGATE_NEXT_ACTIONS = 15
MAX_AGGREGATE_SUMMARY_CHARACTERS = 500


class AgentResultAggregator:
    """Agentを実行せず、計画済み結果を決定的に統合する。"""

    def aggregate(
        self,
        plan: AgentExecutionPlan,
        results: tuple[AgentResult, ...],
    ) -> AgentAggregateResult:
        by_type: dict[AgentType, AgentResult] = {}
        planned_types = {candidate.agent_type for candidate in plan.candidates}
        for result in results:
            if result.agent_type in by_type:
                raise ValueError(
                    f"AgentType「{result.agent_type.value}」の結果が重複しています。"
                )
            if result.agent_type not in planned_types:
                raise ValueError(
                    f"AgentType「{result.agent_type.value}」は計画にありません。"
                )
            by_type[result.agent_type] = result

        ordered = tuple(
            by_type[candidate.agent_type]
            for candidate in plan.candidates
            if candidate.agent_type in by_type
        )
        planned_primary = next(
            (
                by_type.get(candidate.agent_type)
                for candidate in plan.candidates
                if candidate.primary
            ),
            None,
        )
        fallback = next(
            (result for result in ordered if result.status is AgentStatus.COMPLETED),
            None,
        )
        primary_result = planned_primary
        used_fallback = False
        if (
            planned_primary is None
            or planned_primary.status is not AgentStatus.COMPLETED
        ) and fallback is not None:
            primary_result = fallback
            used_fallback = fallback is not planned_primary

        status = self._status(ordered)
        flag_candidates = tuple(
            dict.fromkeys(
                result.flag_candidate
                for result in ordered
                if result.flag_candidate is not None
            )
        )
        primary_flag, confidence = self._primary_flag_and_confidence(
            primary_result,
            ordered,
        )
        evidence = self._evidence(ordered)
        next_actions = tuple(
            dict.fromkeys(action for result in ordered for action in result.next_actions)
        )[:MAX_AGGREGATE_NEXT_ACTIONS]
        conflicts = self._conflicts(ordered, flag_candidates)
        summary = self._summary(ordered, flag_candidates, used_fallback)
        return AgentAggregateResult(
            results=ordered,
            primary_result=primary_result,
            status=status,
            summary=summary,
            flag_candidates=flag_candidates,
            primary_flag=primary_flag,
            confidence=confidence,
            evidence=evidence,
            next_actions=next_actions,
            conflicts=conflicts,
            used_fallback=used_fallback,
            category=plan.category,
        )

    def _status(self, results: tuple[AgentResult, ...]) -> AgentStatus:
        if any(result.status is AgentStatus.COMPLETED for result in results):
            return AgentStatus.COMPLETED
        if any(result.status is AgentStatus.FAILED for result in results):
            return AgentStatus.FAILED
        return AgentStatus.SKIPPED

    def _primary_flag_and_confidence(
        self,
        primary: AgentResult | None,
        results: tuple[AgentResult, ...],
    ) -> tuple[str | None, int | None]:
        if primary is not None and primary.flag_candidate is not None:
            return primary.flag_candidate, primary.confidence
        flagged = next(
            (
                result
                for result in results
                if result.status is AgentStatus.COMPLETED
                and result.flag_candidate is not None
            ),
            None,
        )
        if flagged is not None:
            return flagged.flag_candidate, flagged.confidence
        if primary is not None:
            return None, primary.confidence
        completed = next(
            (result for result in results if result.status is AgentStatus.COMPLETED),
            None,
        )
        return None, completed.confidence if completed is not None else None

    def _evidence(self, results: tuple[AgentResult, ...]) -> tuple[AgentEvidence, ...]:
        evidence: list[AgentEvidence] = []
        seen: set[tuple[str, str, int | None]] = set()
        for result in results:
            for item in result.evidence:
                source = f"[{result.agent_type.value}] {item.source}"
                detail = item.detail[:MAX_AGGREGATE_EVIDENCE_DETAIL_CHARACTERS]
                key = (source, detail, item.confidence)
                if key in seen:
                    continue
                seen.add(key)
                evidence.append(AgentEvidence(source, detail, item.confidence))
                if len(evidence) == MAX_AGGREGATE_EVIDENCE:
                    return tuple(evidence)
        return tuple(evidence)

    def _conflicts(
        self,
        results: tuple[AgentResult, ...],
        flags: tuple[str, ...],
    ) -> tuple[AgentConflict, ...]:
        if len(flags) < 2:
            return ()
        return (
            AgentConflict(
                field="flag_candidate",
                values=flags,
                agents=tuple(
                    result.agent_type
                    for result in results
                    if result.flag_candidate is not None
                ),
            ),
        )

    def _summary(
        self,
        results: tuple[AgentResult, ...],
        flags: tuple[str, ...],
        used_fallback: bool,
    ) -> str:
        completed = sum(result.status is AgentStatus.COMPLETED for result in results)
        failed = sum(result.status is AgentStatus.FAILED for result in results)
        skipped = sum(result.status is AgentStatus.SKIPPED for result in results)
        summary = (
            f"{len(results)}件の専門Agent結果を統合しました。"
            f"完了{completed}件、失敗{failed}件、スキップ{skipped}件。"
            f"Flag候補{len(flags)}件を検出しました。"
        )
        if used_fallback:
            summary += "主担当結果を使用できないため補助Agent結果を採用しました。"
        return summary[:MAX_AGGREGATE_SUMMARY_CHARACTERS]
