import re

from app.codegen.generated_code_result import (
    GeneratedCode,
    GeneratedCodeLanguage,
    GeneratedCodeResult,
    GeneratedCodeStatus,
)

MAX_CODE_BLOCKS = 5
MAX_BLOCK_CHARACTERS = 20_000
MAX_TOTAL_CHARACTERS = 50_000
MAX_PURPOSE_CHARACTERS = 300
_OPENING_FENCE = re.compile(r"^\s*(`{3,})([^`]*)$")
_PYTHON_HINTS = (
    re.compile(r"^\s*(?:async\s+)?def\s+[A-Za-z_]\w*\s*\(", re.MULTILINE),
    re.compile(r"^\s*class\s+[A-Za-z_]\w*", re.MULTILINE),
    re.compile(r"^\s*(?:from\s+\S+\s+import|import\s+\S+)", re.MULTILINE),
    re.compile(r"\bprint\s*\("),
    re.compile(r"^\s*(?:for|while|if|with|try)\b.*:\s*$", re.MULTILINE),
)


class CodeBlockExtractor:
    """AI回答のMarkdown fenced blockからPython候補を抽出する。"""

    def extract(self, response: str) -> GeneratedCodeResult:
        normalized = response.replace("\r\n", "\n").replace("\r", "\n")
        lines = normalized.split("\n")
        items: list[GeneratedCode] = []
        total_characters = 0
        source_index = 0
        line_index = 0
        last_prose: str | None = None

        while line_index < len(lines):
            line = lines[line_index]
            opening = _OPENING_FENCE.match(line)
            if opening is None:
                if line.strip():
                    last_prose = line.strip()
                line_index += 1
                continue

            fence = opening.group(1)
            language_label = opening.group(2).strip().casefold()
            block_lines: list[str] = []
            line_index += 1
            closed = False
            while line_index < len(lines):
                candidate = lines[line_index]
                stripped = candidate.strip()
                if (
                    stripped
                    and set(stripped) == {"`"}
                    and len(stripped) >= len(fence)
                ):
                    closed = True
                    line_index += 1
                    break
                block_lines.append(candidate)
                line_index += 1

            if not closed:
                break

            code = "\n".join(block_lines).rstrip("\n")
            language = self._language(language_label, code)
            if (
                code.strip()
                and language is not None
                and len(code) <= MAX_BLOCK_CHARACTERS
                and total_characters + len(code) <= MAX_TOTAL_CHARACTERS
                and len(items) < MAX_CODE_BLOCKS
            ):
                purpose = (
                    last_prose[:MAX_PURPOSE_CHARACTERS]
                    if last_prose
                    else None
                )
                items.append(
                    GeneratedCode(
                        language=language,
                        code=code,
                        purpose=purpose,
                        source_index=source_index,
                        status=GeneratedCodeStatus.REVIEW_REQUIRED,
                    )
                )
                total_characters += len(code)
            source_index += 1
            last_prose = None

        return GeneratedCodeResult(items=tuple(items))

    def _language(
        self,
        label: str,
        code: str,
    ) -> GeneratedCodeLanguage | None:
        if label in {"python", "py"}:
            return GeneratedCodeLanguage.PYTHON
        if label:
            return None
        if any(pattern.search(code) for pattern in _PYTHON_HINTS):
            return GeneratedCodeLanguage.PYTHON
        return GeneratedCodeLanguage.UNKNOWN
