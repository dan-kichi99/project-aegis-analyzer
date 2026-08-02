from app.execution.execution_analysis_result import (
    ExecutionAnalysisResult,
    ExecutionFlagCandidate,
    ExecutionOutputSource,
)
from app.execution.execution_result import ExecutionStatus, PythonExecutionResult
from app.judge.flag_extractor import FlagExtractor


class ExecutionResultAnalyzer:
    """保持済みの実行出力だけからFlag候補を抽出する純粋処理。"""

    def __init__(self, flag_extractor: FlagExtractor) -> None:
        self._flag_extractor = flag_extractor

    def analyze(self, execution: PythonExecutionResult) -> ExecutionAnalysisResult:
        candidates: list[ExecutionFlagCandidate] = []
        seen: set[str] = set()
        if execution.started:
            self._collect(
                execution.stdout,
                ExecutionOutputSource.STDOUT,
                candidates,
                seen,
            )
            self._collect(
                execution.stderr,
                ExecutionOutputSource.STDERR,
                candidates,
                seen,
            )
        successful = (
            execution.status is ExecutionStatus.COMPLETED
            and execution.exit_code == 0
            and not execution.timed_out
        )
        primary = candidates[0].flag if candidates else None
        return ExecutionAnalysisResult(
            execution=execution,
            flag_candidates=tuple(candidates),
            primary_flag=primary,
            successful_execution=successful,
        )

    def _collect(
        self,
        text: str,
        source: ExecutionOutputSource,
        candidates: list[ExecutionFlagCandidate],
        seen: set[str],
    ) -> None:
        for flag in self._flag_extractor.extract_all(text):
            if flag in seen:
                continue
            seen.add(flag)
            candidates.append(
                ExecutionFlagCandidate(
                    flag=flag,
                    source=source,
                    position=text.find(flag),
                )
            )
