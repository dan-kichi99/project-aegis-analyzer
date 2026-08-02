from app.challenge.challenge_input import ChallengeInput
from app.solver.rsa_parameter_extractor import RsaParameterExtractor
from app.solver.rsa_result import RsaParameters, RsaResult
from app.solver.rsa_solver import RsaSolver

_MAX_INPUT_BLOCKS = 20


class RsaAnalyzer:
    """Challenge内の独立ブロックから最初のRSAセットを診断する。"""

    def __init__(
        self,
        extractor: RsaParameterExtractor | None = None,
        solver: RsaSolver | None = None,
    ) -> None:
        self._extractor = extractor or RsaParameterExtractor()
        self._solver = solver or RsaSolver()

    def analyze(self, challenge: ChallengeInput) -> RsaResult | None:
        incomplete: RsaParameters | None = None
        for text, source in self._blocks(challenge):
            parameters = self._extractor.extract(text, source)
            if parameters is None:
                continue
            if incomplete is None:
                incomplete = parameters
            if self._is_solvable_set(parameters):
                return self._solver.solve(parameters)
        return self._solver.solve(incomplete) if incomplete is not None else None

    def _blocks(self, challenge: ChallengeInput) -> list[tuple[str, str]]:
        blocks = [(challenge.question, "問題文")]
        for file_result in challenge.files:
            if file_result.text_content is not None:
                blocks.append(
                    (
                        file_result.text_content,
                        f"ファイル「{file_result.name}」のテキスト内容",
                    )
                )
            blocks.extend(
                (
                    value,
                    f"ファイル「{file_result.name}」の抽出文字列",
                )
                for value in file_result.strings
            )
            if len(blocks) >= _MAX_INPUT_BLOCKS:
                break
        return blocks[:_MAX_INPUT_BLOCKS]

    def _is_solvable_set(self, parameters: RsaParameters) -> bool:
        if parameters.n is None or parameters.c is None:
            return False
        if parameters.d is not None:
            return True
        return parameters.e is not None
