from dataclasses import replace
from datetime import datetime
from typing import TypeVar

from app.iteration.iteration_action import IterationAction, IterationActionStatus
from app.iteration.iteration_state import (
    MAX_FLAG_CANDIDATES,
    MAX_HYPOTHESES,
    MAX_OPEN_QUESTIONS,
    MAX_PENDING_ACTIONS,
    MAX_STEPS,
    IterationSession,
    IterationSessionStatus,
    IterationStep,
    IterationStopReason,
    OpenQuestionStatus,
)

_T = TypeVar("_T")


class IterationStateManager:
    """外部処理を実行せず、反復解析状態を不変更新する。"""

    def create_session(
        self,
        session_id: str,
        created_at: datetime,
    ) -> IterationSession:
        return IterationSession(
            session_id=session_id,
            status=IterationSessionStatus.ACTIVE,
            current_iteration=0,
            steps=(),
            hypotheses=(),
            open_questions=(),
            pending_actions=(),
            flag_candidates=(),
            primary_flag=None,
            stop_reason=None,
            created_at=created_at,
            updated_at=created_at,
        )

    def append_step(
        self,
        session: IterationSession,
        step: IterationStep,
        updated_at: datetime,
    ) -> IterationSession:
        self._require_active(session)
        self._require_time(session, updated_at)
        if step.iteration_number != session.current_iteration + 1:
            raise ValueError("step.iteration_numberは次の連番で指定してください。")
        if len(session.steps) >= MAX_STEPS:
            raise ValueError(f"stepsは最大{MAX_STEPS}件です。")

        hypotheses = self._merge_by_id(
            session.hypotheses,
            step.hypotheses,
            "hypothesis_id",
        )
        questions = self._merge_by_id(
            session.open_questions,
            step.open_questions,
            "question_id",
        )
        questions = tuple(
            question
            for question in questions
            if question.status is not OpenQuestionStatus.RESOLVED
        )
        actions = self._merge_actions(session.pending_actions, step.proposed_actions)
        flags = self._flags(session, step)
        self._require_limit(hypotheses, MAX_HYPOTHESES, "hypotheses")
        self._require_limit(questions, MAX_OPEN_QUESTIONS, "open_questions")
        self._require_limit(actions, MAX_PENDING_ACTIONS, "pending_actions")
        self._require_limit(flags, MAX_FLAG_CANDIDATES, "flag_candidates")
        return replace(
            session,
            current_iteration=step.iteration_number,
            steps=(*session.steps, step),
            hypotheses=hypotheses,
            open_questions=questions,
            pending_actions=actions,
            flag_candidates=flags,
            primary_flag=session.primary_flag or (flags[0] if flags else None),
            updated_at=updated_at,
        )

    def decide_action(
        self,
        session: IterationSession,
        action_id: str,
        approved: bool,
        updated_at: datetime,
    ) -> IterationSession:
        self._require_active(session)
        self._require_time(session, updated_at)
        selected = next(
            (action for action in session.pending_actions if action.action_id == action_id),
            None,
        )
        if selected is None:
            raise ValueError("指定されたaction_idはpending_actionsにありません。")
        if selected.status is not IterationActionStatus.PROPOSED:
            raise ValueError("判断できるのはPROPOSEDアクションだけです。")
        new_status = (
            IterationActionStatus.APPROVED
            if approved
            else IterationActionStatus.REJECTED
        )
        updated = replace(selected, status=new_status)
        actions = tuple(
            updated if action.action_id == action_id else action
            for action in session.pending_actions
            if approved or action.action_id != action_id
        )
        return replace(session, pending_actions=actions, updated_at=updated_at)

    def stop_session(
        self,
        session: IterationSession,
        reason: IterationStopReason,
        updated_at: datetime,
    ) -> IterationSession:
        self._require_active(session)
        self._require_time(session, updated_at)
        status = IterationSessionStatus.STOPPED
        if reason is IterationStopReason.FLAG_CANDIDATE_FOUND:
            status = IterationSessionStatus.COMPLETED
        elif reason is IterationStopReason.ERROR:
            status = IterationSessionStatus.FAILED
        return replace(
            session,
            status=status,
            stop_reason=reason,
            updated_at=updated_at,
        )

    def complete_action(
        self,
        session: IterationSession,
        action_id: str,
        status: IterationActionStatus,
        updated_at: datetime,
    ) -> IterationSession:
        self._require_active(session)
        self._require_time(session, updated_at)
        if status not in {
            IterationActionStatus.COMPLETED,
            IterationActionStatus.FAILED,
            IterationActionStatus.SKIPPED,
        }:
            raise ValueError("Actionの最終状態はCOMPLETED、FAILED、SKIPPEDだけです。")
        selected = next(
            (action for action in session.pending_actions if action.action_id == action_id),
            None,
        )
        if selected is None:
            raise ValueError("指定されたaction_idはpending_actionsにありません。")
        if selected.status is not IterationActionStatus.APPROVED:
            raise ValueError("最終化できるのはAPPROVED Actionだけです。")
        return replace(
            session,
            pending_actions=tuple(
                action
                for action in session.pending_actions
                if action.action_id != action_id
            ),
            updated_at=updated_at,
        )

    def _merge_by_id(
        self,
        current: tuple[_T, ...],
        incoming: tuple[_T, ...],
        attribute: str,
    ) -> tuple[_T, ...]:
        merged = list(current)
        positions = {getattr(item, attribute): index for index, item in enumerate(merged)}
        for item in incoming:
            identifier = getattr(item, attribute)
            if identifier in positions:
                merged[positions[identifier]] = item
            else:
                positions[identifier] = len(merged)
                merged.append(item)
        return tuple(merged)

    def _merge_actions(
        self,
        current: tuple[IterationAction, ...],
        incoming: tuple[IterationAction, ...],
    ) -> tuple[IterationAction, ...]:
        merged = list(current)
        by_id = {action.action_id: action for action in current}
        for action in incoming:
            existing = by_id.get(action.action_id)
            if existing is not None:
                if existing != action:
                    raise ValueError("同じaction_idに異なる内容を指定できません。")
                continue
            by_id[action.action_id] = action
            if action.status in {
                IterationActionStatus.PROPOSED,
                IterationActionStatus.APPROVED,
            }:
                merged.append(action)
        return tuple(merged)

    def _flags(
        self,
        session: IterationSession,
        step: IterationStep,
    ) -> tuple[str, ...]:
        values = list(session.flag_candidates)
        if step.agent_result is not None:
            values.extend(step.agent_result.flag_candidates)
        if step.execution_result is not None:
            values.extend(item.flag for item in step.execution_result.flag_candidates)
        return tuple(dict.fromkeys(values))

    def _require_active(self, session: IterationSession) -> None:
        if session.status is not IterationSessionStatus.ACTIVE:
            raise ValueError("ACTIVEセッションだけを更新できます。")

    def _require_time(self, session: IterationSession, updated_at: datetime) -> None:
        if updated_at < session.updated_at:
            raise ValueError("updated_atを過去へ戻すことはできません。")

    def _require_limit(self, values: tuple, maximum: int, name: str) -> None:
        if len(values) > maximum:
            raise ValueError(f"{name}は最大{maximum}件です。")
