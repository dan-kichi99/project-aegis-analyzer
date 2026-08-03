from pathlib import PurePath

from app.challenge.challenge_input import ChallengeInput
from app.solver.java_source_result import (
    MAX_JAVA_SOURCE_CANDIDATES,
    JavaSourceResult,
)
from app.solver.java_source_solver import JavaSourceSolver


class JavaSourceAnalyzer:
    def __init__(self, solver: JavaSourceSolver | None = None) -> None:
        self._solver = solver or JavaSourceSolver()

    def analyze(self, challenge: ChallengeInput) -> JavaSourceResult | None:
        candidates = []
        seen: set[tuple[str, str, str | None]] = set()
        truncated = False
        for source, text, java_extension in self._sources(challenge):
            result = self._solver.solve(
                text,
                source,
                java_extension=java_extension,
            )
            if result is None:
                continue
            truncated = truncated or result.truncated
            for candidate in result.candidates:
                key = (candidate.method, candidate.body, candidate.prefix)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(candidate)
                if len(candidates) >= MAX_JAVA_SOURCE_CANDIDATES:
                    return JavaSourceResult(tuple(candidates), True)
        if not candidates:
            return None
        return JavaSourceResult(tuple(candidates), truncated)

    @staticmethod
    def _sources(challenge: ChallengeInput):
        yield "question", challenge.question, False
        for file_result in challenge.files:
            java_extension = PurePath(file_result.name).suffix.casefold() == ".java"
            if file_result.text_content is not None:
                yield file_result.name, file_result.text_content, java_extension
            for index, value in enumerate(file_result.strings):
                yield f"{file_result.name}:strings[{index}]", value, java_extension
