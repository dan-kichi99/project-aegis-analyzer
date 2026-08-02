from dataclasses import replace

from app.codegen.code_safety_result import CodeRiskCategory, CodeRiskLevel
from app.codegen.generated_code_result import (
    GeneratedCode,
    GeneratedCodeLanguage,
    GeneratedCodeResult,
    GeneratedCodeStatus,
)
from app.execution.execution_analysis_result import ExecutionAnalysisResult
from app.presentation.code_execution_models import (
    CodeApprovalDecision,
    CodeApprovalRequest,
    CodeCandidateViewModel,
    CodeExecutionRequest,
    CodeExecutionState,
    ExecutionResultViewModel,
)


class CodeExecutionPresenter:
    def initial_state(self) -> CodeExecutionState:
        return CodeExecutionState((), None, None, (), "生成コード候補はありません。")

    def present_candidates(
        self, generated_code: GeneratedCodeResult | None
    ) -> CodeExecutionState:
        items = generated_code.items if generated_code is not None else ()
        candidates = tuple(self._candidate(item) for item in items)
        return CodeExecutionState(
            candidates,
            None,
            None,
            (),
            "コード候補を選択してください。" if candidates else "生成コード候補はありません。",
        )

    def select_candidate(
        self, state: CodeExecutionState, index: int | None
    ) -> CodeExecutionState:
        if index is None:
            return replace(
                state,
                selected_index=None,
                selected_candidate=None,
                message=(
                    "コード候補を選択してください。"
                    if state.candidates
                    else "生成コード候補はありません。"
                ),
            )
        if isinstance(index, bool) or not 0 <= index < len(state.candidates):
            raise ValueError("indexが範囲外です。")
        candidate = state.candidates[index]
        return replace(
            state,
            selected_index=index,
            selected_candidate=candidate,
            message="コードの危険度と内容を確認してください。",
        )

    def build_approval_request(
        self,
        state: CodeExecutionState,
        decision: CodeApprovalDecision,
    ) -> CodeApprovalRequest:
        if not isinstance(decision, CodeApprovalDecision):
            raise TypeError("decisionが不正です。")
        candidate = self._selected(state)
        allowed = {
            CodeApprovalDecision.APPROVE: candidate.can_approve,
            CodeApprovalDecision.REJECT: candidate.can_reject,
            CodeApprovalDecision.DEFER: candidate.can_defer,
        }
        if not allowed[decision]:
            raise ValueError("このコード候補には指定された判断を行えません。")
        return CodeApprovalRequest(candidate.source_index, decision)

    def build_execution_request(
        self, state: CodeExecutionState
    ) -> CodeExecutionRequest:
        candidate = self._selected(state)
        if not candidate.can_execute:
            raise ValueError("このコード候補は実行要求できません。")
        return CodeExecutionRequest(candidate.source_index)

    def present_execution_results(
        self,
        state: CodeExecutionState,
        analyses: tuple[ExecutionAnalysisResult, ...],
    ) -> CodeExecutionState:
        results = tuple(
            self._execution_result(
                analysis,
                state.candidates[index].source_index
                if index < len(state.candidates)
                else index,
            )
            for index, analysis in enumerate(analyses)
        )
        return replace(state, execution_results=results)

    def _candidate(self, code: GeneratedCode) -> CodeCandidateViewModel:
        safety = code.safety
        risk = safety.overall_risk.value if safety is not None else "unknown"
        parseable = safety.parseable if safety is not None else False
        findings = (
            tuple(self._finding(item) for item in safety.findings)
            if safety is not None
            else ()
        )
        syntax_error = None
        if safety is not None:
            syntax = next(
                (
                    item
                    for item in safety.findings
                    if item.category is CodeRiskCategory.SYNTAX
                ),
                None,
            )
            if syntax is not None:
                syntax_error = syntax.message[:500]
        reviewable = code.status is GeneratedCodeStatus.REVIEW_REQUIRED
        basic = (
            code.language is GeneratedCodeLanguage.PYTHON
            and safety is not None
            and parseable
            and bool(code.code.strip())
            and code.source_index >= 0
        )
        can_approve = basic and reviewable and safety.overall_risk in {
            CodeRiskLevel.LOW,
            CodeRiskLevel.MEDIUM,
        }
        can_execute = (
            basic
            and code.status is GeneratedCodeStatus.APPROVED
            and safety.overall_risk is CodeRiskLevel.LOW
        )
        return CodeCandidateViewModel(
            code.source_index,
            code.language.value,
            code.purpose,
            code.status.value,
            code.code,
            risk,
            parseable,
            findings,
            syntax_error,
            can_approve,
            reviewable,
            reviewable,
            can_execute,
        )

    @staticmethod
    def _finding(finding) -> str:
        symbol = f" / {finding.symbol}" if finding.symbol is not None else ""
        line = f" / {finding.line_number}行目" if finding.line_number is not None else ""
        return (
            f"[{finding.risk_level.value.upper()}] {finding.category.value}"
            f"{symbol}{line} / {finding.message}"
        )[:500]

    @staticmethod
    def _execution_result(
        analysis: ExecutionAnalysisResult, source_index: int
    ) -> ExecutionResultViewModel:
        execution = analysis.execution
        warnings = ["表示されたFlagは候補であり、正解とは限りません。"]
        if not analysis.successful_execution:
            warnings.append("異常終了またはタイムアウト中の途中出力である可能性があります。")
        if execution.output_truncated:
            warnings.append("出力は上限により省略されています。")
        return ExecutionResultViewModel(
            source_index,
            execution.status.value,
            execution.exit_code,
            execution.duration_seconds,
            execution.stdout,
            execution.stderr,
            execution.timed_out,
            execution.output_truncated,
            execution.cleanup_succeeded,
            tuple(item.flag for item in analysis.flag_candidates),
            analysis.primary_flag,
            analysis.successful_execution,
            " ".join(warnings),
        )

    @staticmethod
    def _selected(state: CodeExecutionState) -> CodeCandidateViewModel:
        if state.selected_candidate is None:
            raise ValueError("コード候補が選択されていません。")
        return state.selected_candidate
