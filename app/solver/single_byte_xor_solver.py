from app.judge.flag_extractor import FlagExtractor
from app.solver.xor_result import SingleByteXorResult, XorCandidate

MIN_INPUT_BYTES = 4
MAX_INPUT_BYTES = 65_536
MAX_CANDIDATES = 5
_MIN_PRINTABLE_RATIO = 0.85
_MIN_SCORE = 0.55
_COMMON_ENGLISH_CHARACTERS = frozenset(
    "etaoinshrdluETAOINSHRDLU"
)
_COMMON_TOKENS = (
    "flag",
    "ctf",
    "password",
    "correct",
    "success",
    "enter",
    "key",
    "secret",
)


class SingleByteXorSolver:
    """単一バイト鍵XORを総当たりし、可読性の高い候補だけを返す。"""

    def __init__(self) -> None:
        self._flag_extractor = FlagExtractor()

    def solve(self, data: bytes, source: str) -> SingleByteXorResult:
        if not MIN_INPUT_BYTES <= len(data) <= MAX_INPUT_BYTES:
            return SingleByteXorResult(candidates=())

        candidates: list[XorCandidate] = []
        seen_plaintexts: set[str] = set()
        for key in range(256):
            decoded = bytes(byte ^ key for byte in data)
            try:
                plaintext = decoded.decode("utf-8")
            except UnicodeDecodeError:
                continue

            if key == 0:
                continue

            if plaintext in seen_plaintexts:
                continue
            score = self._score(plaintext)
            if score < _MIN_SCORE:
                continue

            seen_plaintexts.add(plaintext)
            candidates.append(
                XorCandidate(
                    key=key,
                    plaintext=plaintext,
                    score=score,
                    contains_flag=(
                        self._flag_extractor.extract(plaintext) is not None
                    ),
                    source=source,
                )
            )

        candidates.sort(
            key=lambda candidate: (
                not candidate.contains_flag,
                -candidate.score,
                candidate.key,
            )
        )
        return SingleByteXorResult(
            candidates=tuple(candidates[:MAX_CANDIDATES])
        )

    def _score(self, plaintext: str) -> float:
        if not plaintext:
            return 0.0

        printable = sum(
            character.isprintable() or character in "\r\n\t"
            for character in plaintext
        )
        printable_ratio = printable / len(plaintext)
        if printable_ratio < _MIN_PRINTABLE_RATIO:
            return 0.0

        alphanumeric_ratio = sum(
            character.isalnum() or character.isspace()
            for character in plaintext
        ) / len(plaintext)
        common_character_ratio = sum(
            character in _COMMON_ENGLISH_CHARACTERS
            for character in plaintext
        ) / len(plaintext)
        lowered = plaintext.casefold()
        token_bonus = 0.1 if any(
            token in lowered for token in _COMMON_TOKENS
        ) else 0.0
        flag_bonus = (
            0.4
            if self._flag_extractor.extract(plaintext) is not None
            else 0.0
        )
        score = (
            printable_ratio * 0.35
            + alphanumeric_ratio * 0.25
            + common_character_ratio * 0.2
            + token_bonus
            + flag_bonus
        )
        return round(min(1.0, max(0.0, score)), 4)
