import re

from app.external_tools.binwalk_result import (
    MAX_BINWALK_DESCRIPTION_CHARACTERS,
    MAX_BINWALK_ENTRIES,
    BinwalkAnalysis,
    BinwalkEntry,
)

_ENTRY_PATTERN = re.compile(r"^\s*(\d+)\s+(0x[0-9A-Fa-f]+)\s+(.+?)\s*$")


class BinwalkParser:
    def parse(self, output: str) -> BinwalkAnalysis:
        entries: list[BinwalkEntry] = []
        seen: set[tuple[int, str]] = set()
        truncated = False
        for line in output.splitlines():
            match = _ENTRY_PATTERN.match(line)
            if match is None:
                continue
            decimal_offset = int(match.group(1))
            raw_description = match.group(3)
            description = raw_description[:MAX_BINWALK_DESCRIPTION_CHARACTERS]
            identity = (decimal_offset, raw_description)
            if identity in seen:
                continue
            if len(entries) == MAX_BINWALK_ENTRIES:
                truncated = True
                break
            seen.add(identity)
            entries.append(
                BinwalkEntry(
                    decimal_offset=decimal_offset,
                    hexadecimal_offset=match.group(2),
                    description=description,
                )
            )
        return BinwalkAnalysis(tuple(entries), bool(entries), truncated)
