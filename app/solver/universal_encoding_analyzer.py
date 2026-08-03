from collections import deque

from app.challenge.challenge_input import ChallengeInput
from app.judge.flag_extractor import FlagExtractor
from app.solver.universal_encoding_result import (
    MAX_UNIVERSAL_ENCODING_PREVIEW,
    MAX_UNIVERSAL_ENCODING_STEPS,
    UniversalEncodingResult,
    UniversalEncodingStep,
)
from app.solver.universal_encoding_solver import (
    MAX_UNIVERSAL_ENCODING_INPUT,
    UniversalEncodingSolver,
)

MAX_UNIVERSAL_ENCODING_DEPTH = 3
MAX_UNIVERSAL_ENCODING_SOURCES = 100


class UniversalEncodingAnalyzer:
    def __init__(self, solver: UniversalEncodingSolver | None = None) -> None:
        self._solver = solver or UniversalEncodingSolver()
        self._flag_extractor = FlagExtractor()

    def analyze(self, challenge: ChallengeInput) -> UniversalEncodingResult | None:
        steps: list[UniversalEncodingStep] = []
        flags: list[str] = []
        seen_flags: set[str] = set()
        seen_values: set[str] = set()
        truncated = False

        for source, raw_value in self._sources(challenge):
            if len(raw_value) > MAX_UNIVERSAL_ENCODING_INPUT:
                truncated = True
                continue
            value = raw_value.strip()
            if not value or value in seen_values:
                continue
            seen_values.add(value)
            self._append_flags(value, flags, seen_flags)
            queue = deque([(value, 0, ())])
            while queue and len(steps) < MAX_UNIVERSAL_ENCODING_STEPS:
                current, depth, path = queue.popleft()
                if depth >= MAX_UNIVERSAL_ENCODING_DEPTH:
                    continue
                for method, output in self._solver.decode(current):
                    if len(steps) >= MAX_UNIVERSAL_ENCODING_STEPS:
                        truncated = True
                        break
                    next_path = (*path, method)
                    flag = self._flag_extractor.extract(output)
                    input_preview, input_cut = self._preview(current)
                    output_preview, output_cut = self._preview(output)
                    steps.append(
                        UniversalEncodingStep(
                            method=method,
                            depth=depth + 1,
                            source=source,
                            input_preview=input_preview,
                            output_preview=output_preview,
                            flag_candidate=flag,
                            truncated=input_cut or output_cut,
                            transformation_path=next_path,
                        )
                    )
                    self._append_flags(output, flags, seen_flags)
                    if output not in seen_values:
                        seen_values.add(output)
                        queue.append((output, depth + 1, next_path))
            if queue:
                truncated = True
            if len(steps) >= MAX_UNIVERSAL_ENCODING_STEPS:
                truncated = True
                break
        if not steps and not flags:
            return None
        return UniversalEncodingResult(tuple(steps), tuple(flags), truncated)

    @staticmethod
    def _sources(challenge: ChallengeInput) -> list[tuple[str, str]]:
        sources: list[tuple[str, str]] = [("question", challenge.question)]
        for file_result in challenge.files:
            if file_result.text_content is not None:
                sources.append((f"{file_result.name}:text_content", file_result.text_content))
            sources.extend(
                (f"{file_result.name}:strings[{index}]", value)
                for index, value in enumerate(file_result.strings)
            )
        return sources[:MAX_UNIVERSAL_ENCODING_SOURCES]

    @staticmethod
    def _preview(value: str) -> tuple[str, bool]:
        if len(value) <= MAX_UNIVERSAL_ENCODING_PREVIEW:
            return value, False
        return value[:MAX_UNIVERSAL_ENCODING_PREVIEW], True

    def _append_flags(self, value: str, flags: list[str], seen: set[str]) -> None:
        for flag in self._flag_extractor.extract_all(value):
            if flag not in seen and len(flags) < MAX_UNIVERSAL_ENCODING_STEPS:
                seen.add(flag)
                flags.append(flag)
