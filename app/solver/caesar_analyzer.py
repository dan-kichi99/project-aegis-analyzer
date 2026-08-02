import re
import string

from app.solver.caesar_result import CaesarCandidate, CaesarResult
from app.solver.caesar_solver import (
    MAX_INPUT_LENGTH,
    MIN_INPUT_LENGTH,
    CaesarSolver,
)

_MAX_INPUT_SOURCES = 50
_MIN_LETTERS = 4
_MIN_LETTER_RATIO = 0.35
_HEX_PATTERN = re.compile(r"[0-9A-Fa-f]+")
_URL_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://")
_WINDOWS_PATH_PATTERN = re.compile(r"[A-Za-z]:[\\/]")
_BASE64_CHARACTERS = frozenset(string.ascii_letters + string.digits + "+/=")


class CaesarAnalyzer:
    """解析済み文字列からCaesar入力候補を選定し、結果を集約する。"""

    def __init__(self, solver: CaesarSolver | None = None) -> None:
        self._solver = solver or CaesarSolver()

    def analyze(
        self,
        text_content: str | None,
        strings: list[str],
    ) -> CaesarResult:
        sources: list[tuple[str, str, int]] = []
        seen_sources: set[str] = set()
        if text_content is not None:
            for line in text_content.splitlines():
                self._append_source(
                    sources,
                    seen_sources,
                    line,
                    "テキスト内容",
                )
        for value in strings:
            self._append_source(
                sources,
                seen_sources,
                value,
                "抽出文字列",
            )

        matches: list[tuple[CaesarCandidate, int]] = []
        for value, source, source_index in sources:
            result = self._solver.solve(value, source)
            matches.extend(
                (candidate, source_index) for candidate in result.candidates
            )
        matches.sort(
            key=lambda item: (
                not item[0].contains_flag,
                -item[0].score,
                item[0].shift,
                item[1],
            )
        )

        candidates: list[CaesarCandidate] = []
        seen_plaintexts: set[str] = set()
        for candidate, _ in matches:
            if candidate.plaintext not in seen_plaintexts:
                seen_plaintexts.add(candidate.plaintext)
                candidates.append(candidate)
                if len(candidates) >= 5:
                    break
        return CaesarResult(candidates=tuple(candidates))

    def _append_source(
        self,
        sources: list[tuple[str, str, int]],
        seen_sources: set[str],
        value: str,
        source: str,
    ) -> None:
        candidate = value.strip()
        if (
            len(sources) >= _MAX_INPUT_SOURCES
            or candidate in seen_sources
            or not self._is_candidate(candidate)
        ):
            return
        seen_sources.add(candidate)
        sources.append((candidate, source, len(sources)))

    def _is_candidate(self, value: str) -> bool:
        if not MIN_INPUT_LENGTH <= len(value) <= MAX_INPUT_LENGTH:
            return False
        letters = sum(character.isalpha() for character in value)
        if letters < _MIN_LETTERS or letters / len(value) < _MIN_LETTER_RATIO:
            return False
        if _URL_PATTERN.match(value) or _WINDOWS_PATH_PATTERN.match(value):
            return False
        if "/" in value and " " not in value and "{" not in value:
            return False
        if _HEX_PATTERN.fullmatch(value):
            return False
        if (
            len(value) >= 16
            and len(value) % 4 == 0
            and all(character in _BASE64_CHARACTERS for character in value)
        ):
            return False
        printable = sum(
            character.isprintable() or character in "\r\n\t"
            for character in value
        )
        return printable / len(value) >= 0.9
