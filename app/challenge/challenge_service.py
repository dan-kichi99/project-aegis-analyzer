from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from app.analyzer.analyzer import Analyzer
from app.challenge.challenge_input import ChallengeInput
from app.controller.controller import Controller
from app.events.analysis_event import AnalysisEvent, AnalysisEventType
from app.events.event_publisher import EventPublisher
from app.file.file_analysis_result import FileAnalysisResult
from app.file.file_loader import FileLoader
from app.file.static_file_analyzer import StaticFileAnalyzer
from app.file.zip_archive_analyzer import ZipArchiveAnalyzer
from app.judge.flag_extractor import FlagExtractor
from app.judge.judge_result import JudgeResult
from app.optimization.ai_usage_result import ChallengeExecutionResult
from app.optimization.ai_usage_tracker import AiUsageTracker
from app.solver.java_source_analyzer import JavaSourceAnalyzer
from app.solver.new_caesar_analyzer import NewCaesarAnalyzer
from app.solver.python_source_analyzer import PythonSourceAnalyzer
from app.solver.rev_string_analyzer import RevStringAnalyzer
from app.solver.rsa_analyzer import RsaAnalyzer
from app.solver.universal_encoding_analyzer import UniversalEncodingAnalyzer


class ChallengeService:
    """実ファイルパスから解析・コンテキスト構築・AI推論・評価までを一括制御する。"""

    def __init__(
        self,
        controller: Controller,
        analyzer: Analyzer,
        file_loader: FileLoader | None = None,
        file_analyzer: StaticFileAnalyzer | None = None,
        event_publisher: EventPublisher | None = None,
    ) -> None:
        self.controller = controller
        self._analyzer = analyzer
        self.file_loader = file_loader or FileLoader()
        self.file_analyzer = file_analyzer or StaticFileAnalyzer()
        self._zip_analyzer = ZipArchiveAnalyzer(self.file_analyzer)
        self.flag_extractor = FlagExtractor()
        self._rsa_analyzer = RsaAnalyzer()
        self._new_caesar_analyzer = NewCaesarAnalyzer()
        self._universal_encoding_analyzer = UniversalEncodingAnalyzer()
        self._java_source_analyzer = JavaSourceAnalyzer()
        self._python_source_analyzer = PythonSourceAnalyzer()
        self._rev_string_analyzer = RevStringAnalyzer()
        self._event_publisher = event_publisher

    def solve(
        self,
        question: str,
        file_paths: list[str | Path] | None = None,
    ) -> JudgeResult:
        """問題文とファイルパスを受け取り、解析パイプラインを実行する。"""
        return self.solve_with_usage(question, file_paths).result

    def solve_with_usage(
        self,
        question: str,
        file_paths: list[str | Path] | None = None,
        *,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> ChallengeExecutionResult:
        paths = file_paths or []
        self._publish(
            AnalysisEventType.ANALYSIS_STARTED,
            "解析を開始しました。",
            "input",
            {"file_count": len(paths)},
        )
        analysis_results: list[FileAnalysisResult] = []

        for path in paths:
            file_input = self.file_loader.load(path)
            analysis_result = self.file_analyzer.analyze(file_input)
            analysis_results.append(analysis_result)
            if analysis_result.detected_type == "zip":
                analysis_results.extend(
                    self._zip_analyzer.analyze(file_input)
                )

        challenge = ChallengeInput(
            question=question,
            files=analysis_results,
        )
        challenge.rsa_result = self._rsa_analyzer.analyze(challenge)

        local_result = self._find_local_flag(challenge)
        if local_result is not None:
            flag, reason, method = local_result
            result = JudgeResult(
                category=self._analyzer.analyze(question),
                answer="添付ファイル内からFlag候補を検出しました。",
                flag=flag,
                confidence=90,
                reason=reason,
                hypothesis=None,
                next_actions=[],
                gemini_prompt=None,
            )
            self._publish(
                AnalysisEventType.LOCAL_SOLUTION_FOUND,
                "ローカル解析でFlag候補を検出しました。",
                "local_solver",
                {"category": result.category, "method": method},
            )
            self._publish_completed(result)
            return ChallengeExecutionResult(
                result=result,
                ai_usage=AiUsageTracker().snapshot(
                    knowledge_retrieval_count=0,
                    agent_run_count=0,
                    local_solution_avoided_ai=True,
                ),
            )

        if isinstance(self.controller, Controller):
            execution = self.controller.process_challenge_with_usage(
                challenge,
                cancel_requested=cancel_requested,
            )
        else:
            result = self.controller.process_challenge(challenge)
            execution = ChallengeExecutionResult(
                result=result,
                ai_usage=AiUsageTracker().snapshot(
                    knowledge_retrieval_count=1,
                    agent_run_count=0,
                    local_solution_avoided_ai=False,
                ),
            )
        self._publish_completed(execution.result)
        return execution

    def solve_with_cancel(
        self,
        question: str,
        file_paths: list[str | Path] | None,
        cancel_requested: Callable[[], bool],
    ) -> JudgeResult:
        return self.solve_with_usage(
            question,
            file_paths,
            cancel_requested=cancel_requested,
        ).result

    def _find_local_flag(
        self,
        challenge: ChallengeInput,
    ) -> tuple[str, str, str] | None:
        for file_result in challenge.files:
            if (
                file_result.appended_data is not None
                and file_result.appended_data.content is not None
            ):
                appended_text = file_result.appended_data.content.decode(
                    "latin-1"
                )
                flag = self.flag_extractor.extract(appended_text)
                if flag is not None:
                    return (
                        flag,
                        (
                            f"ファイル「{file_result.name}」の"
                            "末尾追加データから検出しました。"
                            f"offset：0x{file_result.appended_data.appended_offset:X} "
                            f"推定形式：{file_result.appended_data.detected_type}"
                        ),
                        "appended_data",
                    )

            if file_result.text_content is not None:
                flag = self.flag_extractor.extract(
                    file_result.text_content
                )
                if flag is not None:
                    return (
                        flag,
                        (
                            f"ファイル「{file_result.name}」の"
                            "テキスト内容から検出しました。"
                        ),
                        "direct_flag",
                    )

            for extracted_string in file_result.strings:
                flag = self.flag_extractor.extract(extracted_string)
                if flag is not None:
                    return (
                        flag,
                        (
                            f"ファイル「{file_result.name}」の"
                            "抽出文字列から検出しました。"
                        ),
                        "direct_flag",
                    )

            if file_result.xor_result is not None:
                for candidate in file_result.xor_result.candidates:
                    flag = self.flag_extractor.extract(candidate.plaintext)
                    if flag is not None:
                        return (
                            flag,
                            (
                                f"ファイル「{file_result.name}」の"
                                "単一バイトXOR解析から検出しました。"
                                f"鍵：0x{candidate.key:02X} "
                                f"検出元：{candidate.source}"
                            ),
                            "single_byte_xor",
                        )

            if file_result.caesar_result is not None:
                for candidate in file_result.caesar_result.candidates:
                    flag = self.flag_extractor.extract(candidate.plaintext)
                    if flag is not None:
                        rot13 = "（ROT13）" if candidate.shift == 13 else ""
                        return (
                            flag,
                            (
                                f"ファイル「{file_result.name}」の"
                                "Caesar解析から検出しました。"
                                f"シフト：{candidate.shift}{rot13} "
                                f"検出元：{candidate.source}"
                            ),
                            "caesar",
                        )

            recursive = file_result.recursive_encoding_result
            if recursive is not None and recursive.flag_candidates:
                flag = recursive.flag_candidates[0]
                step = next(
                    (
                        item
                        for item in recursive.steps
                        if item.flag_candidate == flag
                    ),
                    None,
                )
                route = " → ".join(item.method for item in recursive.steps)
                details = f"Base64深度={step.depth if step else 0}"
                if step is not None and step.caesar_shift is not None:
                    details += f" Caesar shift={step.caesar_shift}"
                return (
                    flag,
                    (
                        f"ファイル「{file_result.name}」の再帰エンコード解析から"
                        f"Flag候補を検出しました。変換経路={route} {details}"
                    ),
                    "recursive_encoding",
                )

        if challenge.rsa_result is not None:
            for attempt in challenge.rsa_result.attempts:
                if attempt.plaintext is None:
                    continue
                flag = self.flag_extractor.extract(attempt.plaintext)
                if flag is not None:
                    return (
                        flag,
                        (
                            f"{challenge.rsa_result.parameters.source}の"
                            "RSA復号結果から検出しました。"
                            f"方式：{attempt.method}"
                        ),
                        "rsa",
                    )

        new_caesar_result = self._new_caesar_analyzer.analyze(challenge)
        if new_caesar_result is not None:
            for candidate in new_caesar_result.candidates:
                flag = self.flag_extractor.extract(candidate.plaintext)
                if flag is not None:
                    return (
                        flag,
                        (
                            "Python源コードからNew Caesar暗号（b16_encode＋"
                            "16文字Alphabet Caesar）を検出し復号しました。"
                            f"鍵：{candidate.key} alphabet：{candidate.alphabet} "
                            f"検出元：{candidate.source}"
                        ),
                        "new_caesar",
                    )

        universal_result = self._universal_encoding_analyzer.analyze(challenge)
        if universal_result is not None and universal_result.flag_candidates:
            step = next(
                (
                    item
                    for flag_candidate in universal_result.flag_candidates
                    for item in universal_result.steps
                    if item.flag_candidate == flag_candidate
                ),
                None,
            )
            if step is None:
                return None
            flag = step.flag_candidate
            if flag is None:
                return None
            route = " -> ".join(step.transformation_path)
            return (
                flag,
                (
                    f"{step.source}からUniversal Encoding解析でFlag候補を検出しました。"
                    f"変換経路={route} 再帰深度={step.depth} "
                    f"最終方式={step.method}"
                ),
                "universal_encoding",
            )

        java_result = self._java_source_analyzer.analyze(challenge)
        if java_result is not None:
            candidate = next(
                (
                    item
                    for item in java_result.candidates
                    if item.flag_candidate is not None
                ),
                None,
            )
            if candidate is not None and candidate.flag_candidate is not None:
                line = (
                    f" 行番号={candidate.line_number}"
                    if candidate.line_number is not None
                    else ""
                )
                return (
                    candidate.flag_candidate,
                    (
                        f"{candidate.source}のJavaソースからFlag候補を検出しました。"
                        f"抽出方式={candidate.method} prefix={candidate.prefix}"
                        f" 比較文字列={candidate.body}{line}"
                    ),
                    "java_source",
                )

        python_result = self._python_source_analyzer.analyze(challenge)
        if python_result is not None:
            candidate = python_result.candidates[0]
            prefix = f" prefix={candidate.prefix}" if candidate.prefix else ""
            return (
                candidate.flag_candidate,
                (
                    f"{candidate.source}のPythonソースからFlag候補を検出しました。"
                    f"復元方式={candidate.method} 変数={candidate.variable_name}"
                    f" 行番号={candidate.line_number}{prefix}"
                ),
                "python_source",
            )

        rev_string_result = self._rev_string_analyzer.analyze(challenge)
        if rev_string_result is not None:
            candidate = rev_string_result.candidates[0]
            route = " -> ".join(candidate.reconstruction_path)
            return (
                candidate.flag_candidate,
                (
                    f"{candidate.source}から分割・難読化文字列を復元しました。"
                    f"復元方式={candidate.method} 使用Strings数={candidate.used_strings} "
                    f"復元経路={route}"
                ),
                "rev_string",
            )

        return None

    def _publish_completed(self, result: JudgeResult) -> None:
        if self._event_publisher is None:
            return
        self._publish(
            AnalysisEventType.ANALYSIS_COMPLETED,
            "解析が完了しました。",
            "completed",
            {
                "solved": result.flag is not None,
                "category": result.category,
            },
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
