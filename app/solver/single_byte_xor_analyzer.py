import re

from app.solver.single_byte_xor_solver import (
    MAX_INPUT_BYTES,
    MIN_INPUT_BYTES,
    SingleByteXorSolver,
)
from app.solver.xor_result import SingleByteXorResult, XorCandidate

_MAX_INPUT_SOURCES = 50
_RAW_BINARY_EXTENSIONS = frozenset({".bin", ".dat", ".enc", ".cipher"})
_COMPACT_HEX_PATTERN = re.compile(r"[0-9A-Fa-f]+")
_SPACED_HEX_PATTERN = re.compile(r"(?:[0-9A-Fa-f]{2}\s+){3,}[0-9A-Fa-f]{2}")


class SingleByteXorAnalyzer:
    """ファイル解析結果から安全なXOR入力候補を選定し、結果を集約する。"""

    def __init__(self, solver: SingleByteXorSolver | None = None) -> None:
        self._solver = solver or SingleByteXorSolver()

    def analyze(
        self,
        content: bytes,
        detected_type: str,
        extension: str,
        text_content: str | None,
        strings: list[str],
    ) -> SingleByteXorResult:
        inputs: list[tuple[bytes, str]] = []
        seen_data: set[bytes] = set()

        if detected_type == "unknown" or extension.casefold() in _RAW_BINARY_EXTENSIONS:
            self._append_input(inputs, seen_data, content, "バイナリデータ")

        sources: list[tuple[str, str]] = []
        if text_content is not None:
            sources.extend(
                (line, "テキスト内容") for line in text_content.splitlines()
            )
        sources.extend((value, "抽出文字列") for value in strings)
        for value, source in sources:
            decoded = self._decode_hex_input(value)
            if decoded is None:
                continue
            self._append_input(inputs, seen_data, decoded, source)
            if len(inputs) >= _MAX_INPUT_SOURCES:
                break

        candidates: list[XorCandidate] = []
        seen_candidates: set[tuple[str, str]] = set()
        for data, source in inputs:
            result = self._solver.solve(data, source)
            for candidate in result.candidates:
                key = (candidate.plaintext, candidate.source)
                if key not in seen_candidates:
                    seen_candidates.add(key)
                    candidates.append(candidate)

        candidates.sort(
            key=lambda candidate: (
                not candidate.contains_flag,
                -candidate.score,
                candidate.key,
            )
        )
        return SingleByteXorResult(candidates=tuple(candidates[:5]))

    def _append_input(
        self,
        inputs: list[tuple[bytes, str]],
        seen_data: set[bytes],
        data: bytes,
        source: str,
    ) -> None:
        if (
            MIN_INPUT_BYTES <= len(data) <= MAX_INPUT_BYTES
            and data not in seen_data
            and len(inputs) < _MAX_INPUT_SOURCES
        ):
            seen_data.add(data)
            inputs.append((data, source))

    def _decode_hex_input(self, value: str) -> bytes | None:
        candidate = value.strip()
        if _SPACED_HEX_PATTERN.fullmatch(candidate):
            if len(candidate) > MAX_INPUT_BYTES * 3:
                return None
            candidate = "".join(candidate.split())
        elif not _COMPACT_HEX_PATTERN.fullmatch(candidate):
            return None
        if (
            len(candidate) < MIN_INPUT_BYTES * 2
            or len(candidate) > MAX_INPUT_BYTES * 2
            or len(candidate) % 2
        ):
            return None
        try:
            return bytes.fromhex(candidate)
        except ValueError:
            return None
