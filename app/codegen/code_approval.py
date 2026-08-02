from dataclasses import dataclass, replace
from enum import Enum

from app.codegen.code_safety_result import CodeRiskLevel
from app.codegen.generated_code_result import (
    GeneratedCode,
    GeneratedCodeLanguage,
    GeneratedCodeStatus,
)


class ApprovalDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


class ApprovalFailureReason(str, Enum):
    NOT_PYTHON = "not_python"
    NOT_REVIEWABLE = "not_reviewable"
    NO_SAFETY_RESULT = "no_safety_result"
    UNPARSEABLE = "unparseable"
    RISK_TOO_HIGH = "risk_too_high"
    INVALID_INDEX = "invalid_index"
    EMPTY_CODE = "empty_code"
    ALREADY_DECIDED = "already_decided"


@dataclass(slots=True, frozen=True)
class CodeApprovalResult:
    accepted: bool
    decision: ApprovalDecision
    code: GeneratedCode
    reason: ApprovalFailureReason | None
    message: str


class CodeApprovalService:
    """生成コードを実行せず、明示された承認状態だけを遷移させる。"""

    def decide(
        self,
        code: GeneratedCode,
        decision: ApprovalDecision,
    ) -> CodeApprovalResult:
        state_failure = self._state_failure(code)
        if state_failure is not None:
            return self._failure(code, decision, state_failure)

        if decision is ApprovalDecision.REJECT:
            rejected = replace(code, status=GeneratedCodeStatus.REJECTED)
            return CodeApprovalResult(
                accepted=True,
                decision=decision,
                code=rejected,
                reason=None,
                message="生成コード候補を拒否しました。",
            )

        failure = self.approval_failure(code)
        if failure is not None:
            return self._failure(code, decision, failure)

        approved = replace(code, status=GeneratedCodeStatus.APPROVED)
        return CodeApprovalResult(
            accepted=True,
            decision=decision,
            code=approved,
            reason=None,
            message="次の隔離実行段階へ進むことを承認しました。コードは未実行です。",
        )

    def approval_failure(
        self,
        code: GeneratedCode,
    ) -> ApprovalFailureReason | None:
        state_failure = self._state_failure(code)
        if state_failure is not None:
            return state_failure
        if code.language is not GeneratedCodeLanguage.PYTHON:
            return ApprovalFailureReason.NOT_PYTHON
        if not isinstance(code.source_index, int) or code.source_index < 0:
            return ApprovalFailureReason.INVALID_INDEX
        if not code.code.strip():
            return ApprovalFailureReason.EMPTY_CODE
        if code.safety is None:
            return ApprovalFailureReason.NO_SAFETY_RESULT
        if not code.safety.parseable:
            return ApprovalFailureReason.UNPARSEABLE
        if code.safety.overall_risk in {
            CodeRiskLevel.HIGH,
            CodeRiskLevel.BLOCKED,
        }:
            return ApprovalFailureReason.RISK_TOO_HIGH
        return None

    def _state_failure(
        self,
        code: GeneratedCode,
    ) -> ApprovalFailureReason | None:
        if code.status in {
            GeneratedCodeStatus.APPROVED,
            GeneratedCodeStatus.REJECTED,
        }:
            return ApprovalFailureReason.ALREADY_DECIDED
        if code.status is not GeneratedCodeStatus.REVIEW_REQUIRED:
            return ApprovalFailureReason.NOT_REVIEWABLE
        return None

    def _failure(
        self,
        code: GeneratedCode,
        decision: ApprovalDecision,
        reason: ApprovalFailureReason,
    ) -> CodeApprovalResult:
        return CodeApprovalResult(
            accepted=False,
            decision=decision,
            code=code,
            reason=reason,
            message="この生成コード候補の状態は変更できません。",
        )

