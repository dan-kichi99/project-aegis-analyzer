from collections.abc import Callable

from app.codegen.code_approval import (
    ApprovalDecision,
    ApprovalFailureReason,
    CodeApprovalService,
)
from app.codegen.generated_code_result import (
    GeneratedCode,
    GeneratedCodeResult,
    GeneratedCodeStatus,
)

MAX_APPROVAL_INPUT_ATTEMPTS = 3


class CliCodeApproval:
    """CLI入力を承認サービスへ橋渡しする。コード実行は行わない。"""

    def __init__(
        self,
        service: CodeApprovalService,
        input_fn: Callable[[str], str] | None = None,
        output_fn: Callable[[str], None] | None = None,
    ) -> None:
        self._service = service
        self._input = input_fn or input
        self._output = output_fn or print

    def review(self, result: GeneratedCodeResult) -> GeneratedCodeResult:
        updated: dict[int, GeneratedCode] = {}
        reviewable = sorted(result.items, key=lambda item: item.source_index)
        for item in reviewable:
            if item.status is not GeneratedCodeStatus.REVIEW_REQUIRED:
                continue
            failure = self._service.approval_failure(item)
            if failure is not None:
                self._show_unavailable(item, failure)
                continue
            updated[id(item)] = self._ask(item)
        return GeneratedCodeResult(
            items=tuple(updated.get(id(item), item) for item in result.items)
        )

    def _ask(self, code: GeneratedCode) -> GeneratedCode:
        self._output(
            f"生成コード候補 {code.source_index + 1} を次の隔離実行段階へ進めますか？"
        )
        self._output("静的検査だけでは安全性を保証できません。")
        self._output("[y] 承認 / [n] 拒否 / [s] 保留")
        for _ in range(MAX_APPROVAL_INPUT_ATTEMPTS):
            response = self._input("> ").strip().casefold()
            if response == "y":
                result = self._service.decide(code, ApprovalDecision.APPROVE)
                self._output(result.message)
                return result.code
            if response == "n":
                result = self._service.decide(code, ApprovalDecision.REJECT)
                self._output(result.message)
                return result.code
            if response == "s":
                self._output("判断を保留しました。コードは未実行です。")
                return code
            self._output("y、n、sのいずれかを入力してください。")
        self._output("入力上限に達したため、判断を保留しました。")
        return code

    def _show_unavailable(
        self,
        code: GeneratedCode,
        failure: ApprovalFailureReason,
    ) -> None:
        if failure is ApprovalFailureReason.RISK_TOO_HIGH and code.safety is not None:
            if code.safety.overall_risk.value == "blocked":
                message = "この候補は実行禁止です。承認入力は行いません。"
            else:
                message = "この候補は高危険度のため承認できません。"
        elif failure is ApprovalFailureReason.NOT_PYTHON:
            message = "この候補はPythonではないため承認できません。"
        else:
            message = "この候補は承認条件を満たしていません。"
        self._output(f"生成コード候補 {code.source_index + 1}：{message}")
