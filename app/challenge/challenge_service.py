from pathlib import Path

from app.challenge.challenge_input import ChallengeInput
from app.controller.controller import Controller
from app.file.file_analysis_result import FileAnalysisResult
from app.file.file_loader import FileLoader
from app.file.static_file_analyzer import StaticFileAnalyzer
from app.judge.judge_result import JudgeResult


class ChallengeService:
    """実ファイルパスから解析・コンテキスト構築・AI推論・評価までを一括制御する。"""

    def __init__(
        self,
        controller: Controller,
        file_loader: FileLoader | None = None,
        file_analyzer: StaticFileAnalyzer | None = None,
    ) -> None:
        self.controller = controller
        self.file_loader = file_loader or FileLoader()
        self.file_analyzer = file_analyzer or StaticFileAnalyzer()

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

        challenge = ChallengeInput(
            question=question,
            files=analysis_results,
        )

        return self.controller.process_challenge(challenge)
