from pathlib import Path

from app.analyzer.analyzer import Analyzer
from app.challenge.challenge_input import ChallengeInput
from app.controller.controller import Controller
from app.file.file_analysis_result import FileAnalysisResult
from app.file.file_loader import FileLoader
from app.file.static_file_analyzer import StaticFileAnalyzer
from app.file.zip_archive_analyzer import ZipArchiveAnalyzer
from app.judge.flag_extractor import FlagExtractor
from app.judge.judge_result import JudgeResult


class ChallengeService:
    """実ファイルパスから解析・コンテキスト構築・AI推論・評価までを一括制御する。"""

    def __init__(
        self,
        controller: Controller,
        analyzer: Analyzer,
        file_loader: FileLoader | None = None,
        file_analyzer: StaticFileAnalyzer | None = None,
    ) -> None:
        self.controller = controller
        self._analyzer = analyzer
        self.file_loader = file_loader or FileLoader()
        self.file_analyzer = file_analyzer or StaticFileAnalyzer()
        self._zip_analyzer = ZipArchiveAnalyzer(self.file_analyzer)
        self.flag_extractor = FlagExtractor()

    def solve(
        self,
        question: str,
        file_paths: list[str | Path] | None = None,
    ) -> JudgeResult:
        """問題文とファイルパスを受け取り、解析パイプラインを実行する。"""
        paths = file_paths or []
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

        local_result = self._find_local_flag(challenge)
        if local_result is not None:
            flag, reason = local_result
            return JudgeResult(
                category=self._analyzer.analyze(question),
                answer="添付ファイル内からFlag候補を検出しました。",
                flag=flag,
                confidence=90,
                reason=reason,
                hypothesis=None,
                next_actions=[],
                gemini_prompt=None,
            )

        return self.controller.process_challenge(challenge)

    def _find_local_flag(
        self,
        challenge: ChallengeInput,
    ) -> tuple[str, str] | None:
        for file_result in challenge.files:
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
                    )

        return None
