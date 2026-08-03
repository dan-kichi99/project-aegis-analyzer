import base64
import binascii
import re

from app.judge.flag_extractor import FlagExtractor
from app.solver.caesar_solver import CaesarSolver
from app.solver.recursive_encoding_result import (
    MAX_RECURSIVE_ENCODING_PREVIEW,
    MAX_RECURSIVE_ENCODING_STEPS,
    RecursiveEncodingResult,
    RecursiveEncodingStep,
)

MAX_RECURSIVE_ENCODING_DEPTH = 3
MAX_RECURSIVE_ENCODING_INPUT = 20_000
MAX_RECURSIVE_ENCODING_SOURCES = 100
MIN_BASE64_LENGTH = 8
_BASE64_PATTERN = re.compile(r"[A-Za-z0-9+/]*={0,2}\Z")


class RecursiveEncodingAnalyzer:
    def __init__(self) -> None:
        self._flag_extractor = FlagExtractor()
        self._caesar_solver = CaesarSolver()

    def analyze(
        self,
        *,
        text_content: str | None,
        strings: list[str],
    ) -> RecursiveEncodingResult | None:
        sources = self._sources(text_content, strings)
        steps: list[RecursiveEncodingStep] = []
        flags: list[str] = []
        seen_flags: set[str] = set()
        seen_values: set[str] = set()
        truncated = False
        for source, raw_value in sources:
            value = raw_value
            if len(value) > MAX_RECURSIVE_ENCODING_INPUT:
                value = value[:MAX_RECURSIVE_ENCODING_INPUT]
                truncated = True
            if not value or value in seen_values:
                continue
            seen_values.add(value)
            self._append_flags(value, flags, seen_flags)
            current = value
            for depth in range(MAX_RECURSIVE_ENCODING_DEPTH + 1):
                normalized = self._normalize_bytes_literal(current)
                if normalized is not None:
                    if not self._append_step(
                        steps, "python_bytes_literal", depth, current, normalized,
                        None, source, truncated,
                        self._flag_extractor.extract(normalized),
                    ):
                        truncated = True
                        break
                    self._append_flags(normalized, flags, seen_flags)
                    current = normalized
                self._append_caesar_steps(
                    steps, flags, seen_flags, current, depth, source
                )
                if len(steps) >= MAX_RECURSIVE_ENCODING_STEPS:
                    truncated = True
                    break
                if depth >= MAX_RECURSIVE_ENCODING_DEPTH:
                    break
                decoded = self._decode_base64(current)
                if decoded is None or decoded in seen_values:
                    break
                seen_values.add(decoded)
                if not self._append_step(
                    steps, "base64", depth + 1, current, decoded,
                    None, source, truncated,
                    self._flag_extractor.extract(decoded),
                ):
                    truncated = True
                    break
                self._append_flags(decoded, flags, seen_flags)
                current = decoded
            if len(steps) >= MAX_RECURSIVE_ENCODING_STEPS:
                truncated = True
                break
        if not steps and not flags:
            return None
        return RecursiveEncodingResult(tuple(steps), tuple(flags), truncated)

    def _sources(
        self, text_content: str | None, strings: list[str]
    ) -> list[tuple[str, str]]:
        values: list[tuple[str, str]] = []
        seen: set[str] = set()
        raw_sources = []
        if text_content is not None:
            raw_sources.extend(
                ("text_content", value)
                for value in (text_content, *text_content.splitlines())
            )
        raw_sources.extend(
            (f"strings[{index}]", value) for index, value in enumerate(strings)
        )
        for source, raw in raw_sources:
            for value in (raw.strip(), *raw.split()):
                if value and value not in seen:
                    seen.add(value)
                    values.append((source, value))
                    if len(values) >= MAX_RECURSIVE_ENCODING_SOURCES:
                        return values
        return values

    @staticmethod
    def _normalize_bytes_literal(value: str) -> str | None:
        stripped = value.strip()
        if len(stripped) < 3 or stripped[0] != "b":
            return None
        quote = stripped[1]
        if quote not in {"'", '"'} or stripped[-1] != quote:
            return None
        normalized = stripped[2:-1]
        return normalized if normalized else None

    @staticmethod
    def _decode_base64(value: str) -> str | None:
        candidate = value.strip()
        if (
            len(candidate) < MIN_BASE64_LENGTH
            or len(candidate) > MAX_RECURSIVE_ENCODING_INPUT
            or not _BASE64_PATTERN.fullmatch(candidate)
        ):
            return None
        candidate += "=" * (-len(candidate) % 4)
        try:
            decoded = base64.b64decode(candidate, validate=True)
            return decoded.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return None

    def _append_caesar_steps(
        self,
        steps: list[RecursiveEncodingStep],
        flags: list[str],
        seen_flags: set[str],
        value: str,
        depth: int,
        source: str,
    ) -> None:
        result = self._caesar_solver.solve(value, source)
        for candidate in result.candidates:
            if not candidate.contains_flag:
                continue
            flag = self._flag_extractor.extract(candidate.plaintext)
            self._append_step(
                steps, "caesar", depth, value, candidate.plaintext,
                candidate.shift, source, False, flag,
            )
            self._append_flags(candidate.plaintext, flags, seen_flags)
            if len(steps) >= MAX_RECURSIVE_ENCODING_STEPS:
                return

    def _append_step(
        self,
        steps: list[RecursiveEncodingStep],
        method: str,
        depth: int,
        input_value: str,
        output_value: str,
        shift: int | None,
        source: str,
        truncated: bool,
        flag: str | None = None,
    ) -> bool:
        if len(steps) >= MAX_RECURSIVE_ENCODING_STEPS:
            return False
        input_preview, input_truncated = self._preview(input_value)
        output_preview, output_truncated = self._preview(output_value)
        steps.append(
            RecursiveEncodingStep(
                method,
                depth,
                input_preview,
                output_preview,
                shift,
                flag,
                source,
                truncated or input_truncated or output_truncated,
            )
        )
        return True

    @staticmethod
    def _preview(value: str) -> tuple[str, bool]:
        if len(value) <= MAX_RECURSIVE_ENCODING_PREVIEW:
            return value, False
        return value[:MAX_RECURSIVE_ENCODING_PREVIEW], True

    def _append_flags(
        self, value: str, flags: list[str], seen: set[str]
    ) -> None:
        for flag in self._flag_extractor.extract_all(value):
            if flag not in seen:
                seen.add(flag)
                flags.append(flag)
