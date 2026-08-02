import re

from app.judge.flag_extractor import FlagExtractor
from app.solver.caesar_result import CaesarCandidate, CaesarResult

MIN_INPUT_LENGTH = 4
MAX_INPUT_LENGTH = 4_096
MAX_CANDIDATES = 5
_MIN_SCORE = 0.5
_MIN_IMPROVEMENT = 0.04
_COMMON_ENGLISH_CHARACTERS = frozenset("etaoinshrdluETAOINSHRDLU")
_COMMON_TOKENS = (
    "flag",
    "ctf",
    "password",
    "secret",
    "correct",
    "success",
    "key",
    "token",
    "enter",
    "access",
    "challenge",
    "hello",
    "world",
    "this",
    "the",
)
_REPEATED_CHARACTER_PATTERN = re.compile(r"(.)\1{4,}")


class CaesarSolver:
    """英字を1〜25文字後方へ戻し、有力なCaesar候補を返す。"""

    def __init__(self) -> None:
        self._flag_extractor = FlagExtractor()

    def solve(self, ciphertext: str, source: str) -> CaesarResult:
        if not MIN_INPUT_LENGTH <= len(ciphertext) <= MAX_INPUT_LENGTH:
            return CaesarResult(candidates=())

        original_score = self._score(ciphertext)
        candidates: list[CaesarCandidate] = []
        seen_plaintexts: set[str] = set()
        for shift in range(1, 26):
            plaintext = self._decode(ciphertext, shift)
            if plaintext in seen_plaintexts:
                continue
            contains_flag = self._flag_extractor.extract(plaintext) is not None
            score = self._score(plaintext)
            if not contains_flag and (
                score < _MIN_SCORE
                or score < original_score + _MIN_IMPROVEMENT
            ):
                continue
            seen_plaintexts.add(plaintext)
            candidates.append(
                CaesarCandidate(
                    shift=shift,
                    plaintext=plaintext,
                    score=score,
                    contains_flag=contains_flag,
                    source=source,
                )
            )

        candidates.sort(
            key=lambda candidate: (
                not candidate.contains_flag,
                -candidate.score,
                candidate.shift,
            )
        )
        return CaesarResult(candidates=tuple(candidates[:MAX_CANDIDATES]))

    def _decode(self, ciphertext: str, shift: int) -> str:
        decoded: list[str] = []
        for character in ciphertext:
            if "A" <= character <= "Z":
                decoded.append(
                    chr((ord(character) - ord("A") - shift) % 26 + ord("A"))
                )
            elif "a" <= character <= "z":
                decoded.append(
                    chr((ord(character) - ord("a") - shift) % 26 + ord("a"))
                )
            else:
                decoded.append(character)
        return "".join(decoded)

    def _score(self, plaintext: str) -> float:
        if not plaintext:
            return 0.0
        printable_ratio = sum(
            character.isprintable() or character in "\r\n\t"
            for character in plaintext
        ) / len(plaintext)
        allowed_ratio = sum(
            character.isalnum()
            or character.isspace()
            or character in "{}_-,.:!?'/\"()[]"
            for character in plaintext
        ) / len(plaintext)
        letters = [character for character in plaintext if character.isalpha()]
        letter_ratio = len(letters) / len(plaintext)
        common_ratio = (
            sum(character in _COMMON_ENGLISH_CHARACTERS for character in letters)
            / len(letters)
            if letters
            else 0.0
        )
        vowel_ratio = (
            sum(character.casefold() in "aeiou" for character in letters)
            / len(letters)
            if letters
            else 0.0
        )
        vowel_score = max(0.0, 1.0 - abs(vowel_ratio - 0.38) / 0.38)
        lowered = plaintext.casefold()
        token_bonus = min(
            0.25,
            sum(token in lowered for token in _COMMON_TOKENS) * 0.08,
        )
        flag_bonus = (
            0.45
            if self._flag_extractor.extract(plaintext) is not None
            else 0.0
        )
        repetition_penalty = (
            0.15 if _REPEATED_CHARACTER_PATTERN.search(plaintext) else 0.0
        )
        score = (
            printable_ratio * 0.15
            + allowed_ratio * 0.15
            + letter_ratio * 0.1
            + common_ratio * 0.15
            + vowel_score * 0.15
            + token_bonus
            + flag_bonus
            - repetition_penalty
        )
        return round(min(1.0, max(0.0, score)), 4)
