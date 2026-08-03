import re
import string

from app.judge.flag_extractor import FlagExtractor
from app.solver.rev_string_result import (
    MAX_REV_STRING_CANDIDATES,
    MAX_REV_STRING_PREVIEW,
    RevStringCandidate,
    RevStringResult,
)
from app.solver.universal_encoding_solver import UniversalEncodingSolver

MAX_REV_STRING_INPUT = 20_000
MAX_REV_STRING_SOURCES = 100
MAX_REV_STRING_FRAGMENTS = 8
_QUOTED = re.compile(r'''["']([^"'\\]{1,500})["']''')
_APPEND = re.compile(r'''\.append\s*\(\s*["']([^"'\\]{1,500})["']\s*\)''')
_CHAR = re.compile(r'''["'](.)["']''')
_INTEGER = re.compile(r"(?<![A-Za-z0-9_])(?:0x[0-9A-Fa-f]+|\d{1,6})(?![A-Za-z0-9_])")


class RevStringSolver:
    def __init__(self) -> None:
        self._flag_extractor = FlagExtractor()
        self._encoding_solver = UniversalEncodingSolver()

    def solve(self, values: list[tuple[str, str]]) -> RevStringResult | None:
        candidates: list[RevStringCandidate] = []
        seen: set[str] = set()
        bounded = values[:MAX_REV_STRING_SOURCES]
        truncated = len(values) > MAX_REV_STRING_SOURCES
        for source, raw in bounded:
            if not raw or len(raw) > MAX_REV_STRING_INPUT:
                truncated = truncated or len(raw) > MAX_REV_STRING_INPUT
                continue
            stripped = raw.strip()
            self._add(candidates, seen, source, "direct_flag", stripped, 1, ("direct",), 95)
            for method, output, path in self._reconstruct(raw):
                self._add(candidates, seen, source, method, output, 1, path, 90)
            if len(candidates) >= MAX_REV_STRING_CANDIDATES:
                return RevStringResult(tuple(candidates), True)
        for start in range(len(bounded)):
            combined = ""
            sources = []
            group = self._source_group(bounded[start][0])
            for offset in range(MAX_REV_STRING_FRAGMENTS):
                index = start + offset
                if index >= len(bounded):
                    break
                source, value = bounded[index]
                if self._source_group(source) != group:
                    break
                fragment = self._fragment(value)
                if fragment is None:
                    break
                combined += fragment
                sources.append(source)
                if offset:
                    self._add(
                        candidates, seen, sources[0], "string_fragments", combined,
                        offset + 1, ("fragments", "concatenate"), 90,
                    )
            if len(candidates) >= MAX_REV_STRING_CANDIDATES:
                return RevStringResult(tuple(candidates), True)
        if not candidates:
            return None
        return RevStringResult(tuple(candidates), truncated)

    def _reconstruct(self, text: str):
        literals = _QUOTED.findall(text)
        if len(literals) >= 2 and ("+" in text or "\n" in text):
            yield "string_concat", "".join(literals), ("literals", "concatenate")
        appended = _APPEND.findall(text)
        if appended:
            yield "string_builder", "".join(appended), ("append", "join")
        if "{" in text and "}" in text:
            chars = _CHAR.findall(text)
            if len(chars) >= 3:
                yield "char_array", "".join(chars), ("char_array", "join")
        integers = self._integers(text)
        if len(integers) >= 3 and all(0 <= item <= 255 for item in integers):
            try:
                decoded = bytes(integers).decode("utf-8")
            except UnicodeDecodeError:
                decoded = ""
            if decoded:
                yield "ascii_integers", decoded, ("integers", "utf8")
        for method, output in self._encoding_solver.decode(text.strip()):
            yield method, output, (method, "utf8")
        reverse = self._reverse_literal(text)
        if reverse is not None:
            yield "reverse", reverse, ("reverse",)
        xor = self._xor(text, integers)
        if xor is not None:
            yield "single_byte_xor", xor, ("integers", "xor", "utf8")

    @staticmethod
    def _reverse_literal(text: str) -> str | None:
        literals = _QUOTED.findall(text)
        if len(literals) != 1:
            return None
        if "[::-1]" in text or ".reverse()" in text:
            return literals[0][::-1]
        return None

    @staticmethod
    def _integers(text: str) -> list[int]:
        if not any(marker in text for marker in ("[", "bytes", "bytearray", "ASCII", "ascii")):
            return []
        return [int(item, 0) for item in _INTEGER.findall(text)[:500]]

    @staticmethod
    def _xor(text: str, values: list[int]) -> str | None:
        if "^" not in text or not values:
            return None
        match = re.search(r"(?:key\s*=|\^)\s*(0x[0-9A-Fa-f]+|\d{1,3})", text)
        if match is None:
            return None
        key = int(match.group(1), 0)
        if not 0 <= key <= 255:
            return None
        array_match = re.search(r"\[([^\]]+)\]", text)
        if array_match is None:
            return None
        payload = [int(item, 0) for item in _INTEGER.findall(array_match.group(1))]
        try:
            return bytes(item ^ key for item in payload).decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            return None

    def _add(self, candidates, seen, source, method, value, used, path, confidence):
        flag = self._flag(value)
        if flag is None or flag in seen or len(candidates) >= MAX_REV_STRING_CANDIDATES:
            return
        seen.add(flag)
        candidates.append(
            RevStringCandidate(
                source=source,
                method=method,
                reconstructed=value,
                flag_candidate=flag,
                used_strings=used,
                reconstruction_path=path,
                confidence=confidence,
                preview=value[:MAX_REV_STRING_PREVIEW],
                truncated=len(value) > MAX_REV_STRING_PREVIEW,
            )
        )

    def _flag(self, value: str) -> str | None:
        known = self._flag_extractor.extract(value)
        if known == value:
            return known
        if not value.endswith("}") or value.count("{") != 1:
            return None
        prefix, body = value[:-1].split("{", 1)
        if not body or not 3 <= len(prefix) <= 32:
            return None
        allowed = string.ascii_letters + string.digits + "_-"
        if any(char.isspace() or char in "\"'{}" for char in body):
            return None
        return value if all(char in allowed for char in prefix) else None

    @staticmethod
    def _fragment(value: str) -> str | None:
        stripped = value.strip()
        match = _QUOTED.fullmatch(stripped)
        fragment = match.group(1) if match else stripped
        if not fragment or len(fragment) > 500 or any(char.isspace() for char in fragment):
            return None
        return fragment

    @staticmethod
    def _source_group(source: str) -> str:
        if source == "question":
            return source
        if ":strings[" in source:
            return source.split(":strings[", 1)[0]
        if "." in source:
            return source
        return "fragments"
