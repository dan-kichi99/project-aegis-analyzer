from app.challenge.challenge_input import ChallengeInput
from app.solver.rev_string_result import RevStringResult
from app.solver.rev_string_solver import RevStringSolver


class RevStringAnalyzer:
    def __init__(self, solver: RevStringSolver | None = None) -> None:
        self._solver = solver or RevStringSolver()

    def analyze(self, challenge: ChallengeInput) -> RevStringResult | None:
        values = [("question", challenge.question)]
        for file_result in challenge.files:
            if file_result.text_content is not None:
                values.append((file_result.name, file_result.text_content))
            values.extend(
                (f"{file_result.name}:strings[{index}]", value)
                for index, value in enumerate(file_result.strings)
            )
        return self._solver.solve(values)
