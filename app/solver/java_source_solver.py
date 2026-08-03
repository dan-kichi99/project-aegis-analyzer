import re

from app.judge.flag_extractor import FlagExtractor
from app.solver.java_source_result import (
    MAX_JAVA_SOURCE_CANDIDATES,
    MAX_JAVA_SOURCE_PREVIEW,
    JavaSourceCandidate,
    JavaSourceResult,
)

MAX_JAVA_SOURCE_INPUT = 100_000
_JAVA_MARKERS = (
    "class ", "public ", "static ", "void main", "String ",
    "boolean ", "return ", ".equals(", ".substring(", ".charAt(",
    "StringBuilder", "System.out",
)
_PREFIXES = (
    "picoCTF{", "FLAG{", "CTF{", "HTB{", "DUCTF{", "AIS3{",
    "SECCON{", "TSGCTF{", "TCP1P{",
)
_LITERAL = r'"([^"\\]*)"'
_EQUALS_PATTERNS = (
    re.compile(rf"[A-Za-z_$][\w$]*\.equals\s*\(\s*{_LITERAL}\s*\)"),
    re.compile(rf"{_LITERAL}\s*\.equals\s*\(\s*[A-Za-z_$][\w$]*\s*\)"),
)
_IGNORE_CASE_PATTERNS = (
    re.compile(rf"[A-Za-z_$][\w$]*\.equalsIgnoreCase\s*\(\s*{_LITERAL}\s*\)"),
    re.compile(rf"{_LITERAL}\s*\.equalsIgnoreCase\s*\(\s*[A-Za-z_$][\w$]*\s*\)"),
)


class JavaSourceSolver:
    def __init__(self) -> None:
        self._flag_extractor = FlagExtractor()

    def solve(
        self,
        text: str,
        source: str,
        *,
        java_extension: bool = False,
    ) -> JavaSourceResult | None:
        if not text:
            return None
        truncated = len(text) > MAX_JAVA_SOURCE_INPUT
        bounded = text[:MAX_JAVA_SOURCE_INPUT]
        code = self._remove_comments(bounded)
        if not java_extension and sum(marker in code for marker in _JAVA_MARKERS) < 2:
            return None
        prefix = self._detect_prefix(code)
        candidates: list[JavaSourceCandidate] = []
        seen: set[tuple[str, str, str | None]] = set()
        for method, patterns in (
            ("java_equals", _EQUALS_PATTERNS),
            ("java_equals_ignore_case", _IGNORE_CASE_PATTERNS),
        ):
            matches = sorted(
                (match for pattern in patterns for match in pattern.finditer(code)),
                key=lambda match: match.start(),
            )
            for match in matches:
                body = match.group(1)
                flag = self._make_flag(prefix, body)
                key = (method, body, prefix)
                if not body or key in seen:
                    continue
                seen.add(key)
                preview = match.group(0)[:MAX_JAVA_SOURCE_PREVIEW]
                candidates.append(
                    JavaSourceCandidate(
                        source=source,
                        prefix=prefix,
                        body=body,
                        flag_candidate=flag,
                        method=method,
                        confidence=90 if flag else 70,
                        line_number=code.count("\n", 0, match.start()) + 1,
                        evidence_preview=preview,
                        truncated=(
                            truncated
                            or len(match.group(0)) > MAX_JAVA_SOURCE_PREVIEW
                        ),
                    )
                )
                if len(candidates) >= MAX_JAVA_SOURCE_CANDIDATES:
                    return JavaSourceResult(tuple(candidates), True)
        if not candidates:
            return None
        return JavaSourceResult(tuple(candidates), truncated)

    def _make_flag(self, prefix: str | None, body: str) -> str | None:
        if prefix is None:
            return self._flag_extractor.extract(body)
        candidate = f"{prefix}{body}}}"
        return self._flag_extractor.extract(candidate)

    @staticmethod
    def _detect_prefix(code: str) -> str | None:
        for prefix in _PREFIXES:
            literal = f'"{prefix}"'
            if literal in code and ".substring(" in code and ".length()" in code:
                return prefix
        return None

    @staticmethod
    def _remove_comments(text: str) -> str:
        output = list(text)
        index = 0
        quote: str | None = None
        while index < len(text):
            char = text[index]
            if quote is not None:
                if char == "\\":
                    index += 2
                    continue
                if char == quote:
                    quote = None
                index += 1
                continue
            if char in {'"', "'"}:
                quote = char
                index += 1
                continue
            if text.startswith("//", index):
                end = text.find("\n", index)
                end = len(text) if end < 0 else end
                for position in range(index, end):
                    output[position] = " "
                index = end
                continue
            if text.startswith("/*", index):
                end = text.find("*/", index + 2)
                end = len(text) if end < 0 else end + 2
                for position in range(index, end):
                    if output[position] != "\n":
                        output[position] = " "
                index = end
                continue
            index += 1
        return "".join(output)
