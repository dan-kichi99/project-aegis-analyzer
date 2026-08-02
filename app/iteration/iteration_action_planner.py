from app.agents.agent_aggregate_result import AgentAggregateResult
from app.codegen.code_safety_result import CodeRiskLevel
from app.codegen.generated_code_result import GeneratedCodeLanguage, GeneratedCodeStatus
from app.execution.execution_analysis_result import ExecutionAnalysisResult
from app.iteration.iteration_action import (
    IterationAction,
    IterationActionStatus,
    IterationActionType,
)
from app.iteration.iteration_state import (
    AnalysisHypothesis,
    HypothesisStatus,
    OpenQuestion,
    OpenQuestionStatus,
)
from app.judge.judge_result import JudgeResult

MAX_PLANNED_ACTIONS = 20


class IterationActionPlanner:
    """構造化済み結果から、実行を伴わず次Action候補を生成する。"""

    def plan(
        self,
        *,
        agent_result: AgentAggregateResult | None,
        judge_result: JudgeResult | None,
        execution_result: ExecutionAnalysisResult | None,
        hypotheses: tuple[AnalysisHypothesis, ...],
        open_questions: tuple[OpenQuestion, ...],
        existing_actions: tuple[IterationAction, ...] = (),
    ) -> tuple[IterationAction, ...]:
        existing = self._existing_by_id(existing_actions)
        candidates: dict[str, IterationAction] = {}

        self._flag_actions(candidates, agent_result, judge_result, execution_result)
        self._agent_actions(candidates, agent_result)
        self._code_actions(candidates, judge_result)
        self._execution_actions(candidates, execution_result)
        self._hypothesis_actions(candidates, hypotheses)
        self._question_actions(candidates, open_questions)

        planned: list[IterationAction] = []
        for action in candidates.values():
            previous = existing.get(action.action_id)
            if previous is not None:
                if previous != action:
                    raise ValueError(
                        f"既存action_id「{action.action_id}」の内容が異なります。"
                    )
                continue
            planned.append(action)
        planned.sort(key=lambda action: (-action.priority, action.action_id))
        return tuple(planned[:MAX_PLANNED_ACTIONS])

    def _flag_actions(
        self,
        candidates: dict[str, IterationAction],
        agent_result: AgentAggregateResult | None,
        judge_result: JudgeResult | None,
        execution_result: ExecutionAnalysisResult | None,
    ) -> None:
        flags: list[str] = []
        conflict_count = 0
        if agent_result is not None:
            flags.extend(agent_result.flag_candidates)
            conflict_count = len(agent_result.conflicts)
        if execution_result is not None:
            flags.extend(item.flag for item in execution_result.flag_candidates)
        if judge_result is not None and judge_result.flag is not None:
            flags.append(judge_result.flag)
        unique_flags = tuple(dict.fromkeys(flags))
        if len(unique_flags) > 1 or conflict_count:
            self._add(
                candidates,
                self._action(
                    "manual-review:flag-conflict",
                    IterationActionType.MANUAL_REVIEW,
                    100,
                    "Flag候補の競合を確認する",
                    "複数のFlag候補が競合しています。根拠を確認してください。",
                    "Flag候補を正解と確定する前に人手で照合する必要があります。",
                    True,
                    {
                        "candidate_count": len(unique_flags),
                        "conflict_count": conflict_count,
                    },
                ),
            )
        elif unique_flags:
            self._add(
                candidates,
                self._action(
                    "manual-review:flag-candidate",
                    IterationActionType.MANUAL_REVIEW,
                    90,
                    "Flag候補を確認する",
                    "検出されたFlag候補を問題内容と照合してください。",
                    "Flag候補は自動提出せず、人手で確認します。",
                    True,
                    {"candidate_count": 1, "conflict_count": 0},
                ),
            )

    def _agent_actions(
        self,
        candidates: dict[str, IterationAction],
        agent_result: AgentAggregateResult | None,
    ) -> None:
        if agent_result is None:
            return
        for index, _ in enumerate(agent_result.next_actions):
            self._add(
                candidates,
                self._action(
                    f"manual-review:agent-next-action:{index}",
                    IterationActionType.MANUAL_REVIEW,
                    50,
                    "専門Agentの次手を確認する",
                    "専門Agentが提示した次の手順を人手で確認してください。",
                    "自然言語の手順を自動実行しないための確認候補です。",
                    True,
                    {"source_index": index},
                ),
            )

    def _code_actions(
        self,
        candidates: dict[str, IterationAction],
        judge_result: JudgeResult | None,
    ) -> None:
        if judge_result is None or judge_result.generated_code is None:
            return
        for code in judge_result.generated_code.items:
            safety = code.safety
            risk = safety.overall_risk if safety is not None else None
            metadata = {
                "source_index": code.source_index,
                "risk_level": risk.value if risk is not None else "unknown",
            }
            if code.status is GeneratedCodeStatus.REJECTED:
                continue
            if code.language is GeneratedCodeLanguage.UNKNOWN:
                self._add_code_manual_review(candidates, code.source_index, metadata)
                continue
            if risk in {CodeRiskLevel.HIGH, CodeRiskLevel.BLOCKED}:
                self._add_code_manual_review(candidates, code.source_index, metadata)
                continue
            if code.status is GeneratedCodeStatus.REVIEW_REQUIRED and risk in {
                CodeRiskLevel.LOW,
                CodeRiskLevel.MEDIUM,
            }:
                self._add(
                    candidates,
                    self._action(
                        f"review-code:{code.source_index}",
                        IterationActionType.REVIEW_CODE,
                        90,
                        "生成コードをレビューする",
                        "生成されたPythonコードの内容と安全性を確認してください。",
                        "LOWまたはMEDIUMでも自動承認しません。",
                        True,
                        metadata,
                    ),
                )
            elif code.status is GeneratedCodeStatus.APPROVED:
                if risk is CodeRiskLevel.LOW:
                    self._add(
                        candidates,
                        self._action(
                            f"execute-approved-code:{code.source_index}",
                            IterationActionType.EXECUTE_APPROVED_CODE,
                            90,
                            "承認済みコードの実行を再確認する",
                            "承認済みLOWコードを制限付きで実行する候補です。",
                            "実行には別の明示承認が必要です。",
                            True,
                            metadata,
                        ),
                    )
                else:
                    self._add_code_manual_review(candidates, code.source_index, metadata)

    def _add_code_manual_review(
        self,
        candidates: dict[str, IterationAction],
        source_index: int,
        metadata: dict[str, object],
    ) -> None:
        self._add(
            candidates,
            self._action(
                f"manual-review:code:{source_index}",
                IterationActionType.MANUAL_REVIEW,
                95,
                "生成コードを手動確認する",
                "自動実行できない生成コードを手動で確認してください。",
                "危険度または言語の条件が安全な実行要件を満たしていません。",
                True,
                metadata,
            ),
        )

    def _execution_actions(
        self,
        candidates: dict[str, IterationAction],
        execution_result: ExecutionAnalysisResult | None,
    ) -> None:
        if execution_result is None or execution_result.flag_candidates:
            return
        execution = execution_result.execution
        if not execution_result.successful_execution or execution.output_truncated:
            self._add(
                candidates,
                self._action(
                    "manual-review:execution-output",
                    IterationActionType.MANUAL_REVIEW,
                    85,
                    "実行結果を手動確認する",
                    "正常完了していない、または省略された実行結果を確認してください。",
                    "コードを自動再実行せず、既存の構造化結果を確認します。",
                    True,
                    {
                        "execution_status": execution.status.value,
                        "output_truncated": execution.output_truncated,
                    },
                ),
            )

    def _hypothesis_actions(
        self,
        candidates: dict[str, IterationAction],
        hypotheses: tuple[AnalysisHypothesis, ...],
    ) -> None:
        for hypothesis in hypotheses:
            if hypothesis.status not in {HypothesisStatus.OPEN, HypothesisStatus.SUPPORTED}:
                continue
            confidence = hypothesis.confidence
            high_confidence = confidence is not None and confidence >= 75
            action_type = (
                IterationActionType.RUN_LOCAL_ANALYSIS
                if high_confidence
                else IterationActionType.MANUAL_REVIEW
            )
            self._add(
                candidates,
                self._action(
                    f"hypothesis:{hypothesis.hypothesis_id}",
                    action_type,
                    75 if high_confidence else 50,
                    "仮説を追加検証する",
                    "構造化された仮説を追加検証してください。",
                    "仮説の状態とconfidenceに基づく候補です。",
                    not high_confidence,
                    {
                        "hypothesis_id": hypothesis.hypothesis_id,
                        "confidence": confidence,
                    },
                ),
            )

    def _question_actions(
        self,
        candidates: dict[str, IterationAction],
        questions: tuple[OpenQuestion, ...],
    ) -> None:
        for question in questions:
            if question.status is OpenQuestionStatus.RESOLVED:
                continue
            blocked = question.status is OpenQuestionStatus.BLOCKED
            self._add(
                candidates,
                self._action(
                    f"request-input:{question.question_id}"
                    if blocked
                    else f"manual-review:question:{question.question_id}",
                    IterationActionType.REQUEST_USER_INPUT
                    if blocked
                    else IterationActionType.MANUAL_REVIEW,
                    70 if blocked else 60,
                    "未解決項目への入力を確認する"
                    if blocked
                    else "未解決項目を確認する",
                    "未解決項目を解消するための情報を確認してください。",
                    "質問本文を解析せず、構造化された状態だけから生成しました。",
                    not blocked,
                    {"question_id": question.question_id},
                ),
            )

    def _action(
        self,
        action_id: str,
        action_type: IterationActionType,
        priority: int,
        title: str,
        description: str,
        reason: str,
        requires_user_approval: bool,
        metadata: dict[str, object],
    ) -> IterationAction:
        return IterationAction(
            action_id=action_id,
            action_type=action_type,
            status=IterationActionStatus.PROPOSED,
            title=title,
            description=description,
            priority=priority,
            reason=reason,
            target_agent=None,
            requires_user_approval=requires_user_approval,
            metadata=metadata,
        )

    def _add(
        self,
        candidates: dict[str, IterationAction],
        action: IterationAction,
    ) -> None:
        existing = candidates.get(action.action_id)
        if existing is not None and existing != action:
            raise ValueError(f"action_id「{action.action_id}」の内容が異なります。")
        candidates[action.action_id] = action

    def _existing_by_id(
        self,
        actions: tuple[IterationAction, ...],
    ) -> dict[str, IterationAction]:
        result: dict[str, IterationAction] = {}
        for action in actions:
            existing = result.get(action.action_id)
            if existing is not None and existing != action:
                raise ValueError(
                    f"既存action_id「{action.action_id}」の内容が異なります。"
                )
            result[action.action_id] = action
        return result
