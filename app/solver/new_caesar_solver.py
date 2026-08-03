from app.judge.flag_extractor import FlagExtractor
from app.solver.new_caesar_result import NewCaesarCandidate, NewCaesarResult

_ALPHABET_SIZE = 16


class NewCaesarSolver:
    """b16_encode＋16文字AlphabetのCaesar変種を鍵総当たり（16通り）で復号する。"""

    def __init__(self, flag_extractor: FlagExtractor | None = None) -> None:
        self._flag_extractor = flag_extractor or FlagExtractor()

    def solve(self, ciphertext: str, alphabet: str, source: str) -> NewCaesarResult:
        if len(alphabet) != _ALPHABET_SIZE or len(set(alphabet)) != _ALPHABET_SIZE:
            return NewCaesarResult(())
        if not ciphertext or len(ciphertext) % 2 != 0:
            return NewCaesarResult(())
        index = {char: position for position, char in enumerate(alphabet)}
        if any(char not in index for char in ciphertext):
            return NewCaesarResult(())

        candidates: list[NewCaesarCandidate] = []
        for key in range(_ALPHABET_SIZE):
            plaintext = self._decode(ciphertext, alphabet, index, key)
            if plaintext is None:
                continue
            flag = self._flag_extractor.extract(plaintext)
            candidates.append(
                NewCaesarCandidate(key, alphabet, plaintext, flag is not None, source)
            )
        candidates.sort(key=lambda item: (not item.contains_flag, item.key))
        return NewCaesarResult(tuple(candidates))

    @staticmethod
    def _decode(
        ciphertext: str,
        alphabet: str,
        index: dict[str, int],
        key: int,
    ) -> str | None:
        nibbles = [(index[char] - key) % _ALPHABET_SIZE for char in ciphertext]
        try:
            raw = bytes(
                (nibbles[i] << 4) | nibbles[i + 1] for i in range(0, len(nibbles), 2)
            )
            return raw.decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            return None
