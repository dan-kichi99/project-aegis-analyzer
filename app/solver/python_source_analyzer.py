from pathlib import PurePath

from app.challenge.challenge_input import ChallengeInput
from app.solver.python_source_result import (
    MAX_PYTHON_SOURCE_CANDIDATES,
    PythonSourceResult,
)
from app.solver.python_source_solver import PythonSourceSolver


class PythonSourceAnalyzer:
    def __init__(self, solver: PythonSourceSolver | None = None) -> None:
        self._solver = solver or PythonSourceSolver()

    def analyze(self, challenge: ChallengeInput) -> PythonSourceResult | None:
        candidates = []
        seen: set[str] = set()
        truncated = False
        for source, text, python_extension in self._sources(challenge):
            result = self._solver.solve(text, source, python_extension=python_extension)
            if result is None:
                continue
            truncated = truncated or result.truncated
            for candidate in result.candidates:
                if candidate.flag_candidate in seen:
                    continue
                seen.add(candidate.flag_candidate)
                candidates.append(candidate)
                if len(candidates) >= MAX_PYTHON_SOURCE_CANDIDATES:
                    return PythonSourceResult(tuple(candidates), True)
        if not candidates:
            return None
        return PythonSourceResult(tuple(candidates), truncated)

    @staticmethod
    def _sources(challenge: ChallengeInput):
        yield "question", challenge.question, False
        for file_result in challenge.files:
            is_python = PurePath(file_result.name).suffix.casefold() == ".py"
            if file_result.text_content is not None:
                yield file_result.name, file_result.text_content, is_python
            for index, value in enumerate(file_result.strings):
                yield f"{file_result.name}:strings[{index}]", value, is_python
