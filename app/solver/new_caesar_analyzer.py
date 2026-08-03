import re

from app.challenge.challenge_input import ChallengeInput
from app.solver.new_caesar_result import NewCaesarResult
from app.solver.new_caesar_solver import NewCaesarSolver

_REQUIRED_MARKERS = ("ALPHABET", "LOWERCASE_OFFSET", "b16_encode", "shift(")
_ALPHABET_PATTERN = re.compile(r"ALPHABET\s*=\s*(['\"])(.*?)\1")
_ALPHABET_SIZE = 16
_MAX_BLOCKS = 20
_MIN_CIPHERTEXT_LENGTH = 8


class NewCaesarAnalyzer:
    """Python源コードからNew Caesar（b16_encode＋16文字Alphabet）を検出しローカル復号する。"""

    def __init__(self, solver: NewCaesarSolver | None = None) -> None:
        self._solver = solver or NewCaesarSolver()

    def analyze(self, challenge: ChallengeInput) -> NewCaesarResult | None:
        blocks = self._blocks(challenge)
        alphabet = self._detect_alphabet(blocks)
        if alphabet is None:
            return None

        seen: set[tuple[int, str]] = set()
        candidates = []
        for text, source in blocks:
            for token in self._candidate_tokens(text, alphabet):
                result = self._solver.solve(token, alphabet, source)
                for candidate in result.candidates:
                    key = (candidate.key, candidate.plaintext)
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append(candidate)
        if not candidates:
            return None
        candidates.sort(key=lambda item: (not item.contains_flag, item.key))
        return NewCaesarResult(tuple(candidates))

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
                (value, f"ファイル「{file_result.name}」の抽出文字列")
                for value in file_result.strings
            )
            if len(blocks) >= _MAX_BLOCKS:
                break
        return blocks[:_MAX_BLOCKS]

    def _detect_alphabet(self, blocks: list[tuple[str, str]]) -> str | None:
        for text, _source in blocks:
            if not all(marker in text for marker in _REQUIRED_MARKERS):
                continue
            match = _ALPHABET_PATTERN.search(text)
            if match is None:
                continue
            candidate = match.group(2)
            if len(candidate) == _ALPHABET_SIZE and len(set(candidate)) == _ALPHABET_SIZE:
                return candidate
        return None

    @staticmethod
    def _candidate_tokens(text: str, alphabet: str) -> list[str]:
        allowed = set(alphabet)
        tokens: list[str] = []
        current: list[str] = []
        for char in text:
            if char in allowed:
                current.append(char)
                continue
            if len(current) >= _MIN_CIPHERTEXT_LENGTH and len(current) % 2 == 0:
                tokens.append("".join(current))
            current = []
        if len(current) >= _MIN_CIPHERTEXT_LENGTH and len(current) % 2 == 0:
            tokens.append("".join(current))
        return tokens
