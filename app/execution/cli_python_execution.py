from collections.abc import Callable

from app.codegen.code_safety_result import CodeRiskLevel
from app.codegen.generated_code_result import (
    GeneratedCode,
    GeneratedCodeLanguage,
    GeneratedCodeResult,
    GeneratedCodeStatus,
)
from app.execution.execution_result import PythonExecutionResult
from app.execution.python_execution_runner import PythonExecutionRunner

MAX_EXECUTION_INPUT_ATTEMPTS = 3


class CliPythonExecution:
    """承認とは別の明示入力を、制限付きRunnerへ橋渡しする。"""

    def __init__(
        self,
        runner: PythonExecutionRunner,
        input_fn: Callable[[str], str] | None = None,
        output_fn: Callable[[str], None] | None = None,
    ) -> None:
        self._runner = runner
        self._input = input_fn or input
        self._output = output_fn or print

    def run_approved(
        self,
        generated: GeneratedCodeResult,
    ) -> tuple[PythonExecutionResult, ...]:
        results: list[PythonExecutionResult] = []
        for code in sorted(generated.items, key=lambda item: item.source_index):
            if not self._is_executable(code):
                continue
            self._show_warning(code)
            if self._confirmed():
                results.append(self._runner.run(code))
            else:
                self._output("コードは実行しませんでした。")
        return tuple(results)

    def _is_executable(self, code: GeneratedCode) -> bool:
        return (
            code.language is GeneratedCodeLanguage.PYTHON
            and code.status is GeneratedCodeStatus.APPROVED
            and code.safety is not None
            and code.safety.parseable
            and code.safety.overall_risk is CodeRiskLevel.LOW
            and bool(code.code.strip())
            and isinstance(code.source_index, int)
            and code.source_index >= 0
        )

    def _show_warning(self, code: GeneratedCode) -> None:
        self._output(f"候補{code.source_index + 1}は承認済みです。")
        self._output("制限付き別プロセスで実行しますか？")
        self._output("この実行環境は完全なサンドボックスではありません。")
        self._output(
            "ネットワークおよびOS全体へのアクセスを完全には遮断できません。"
        )
        self._output("[y] 実行 / [n] 実行しない")

    def _confirmed(self) -> bool:
        for _ in range(MAX_EXECUTION_INPUT_ATTEMPTS):
            response = self._input("> ").strip().casefold()
            if response == "y":
                return True
            if response == "n":
                return False
            self._output("yまたはnを入力してください。")
        self._output("入力上限に達したため、コードは実行しません。")
        return False

