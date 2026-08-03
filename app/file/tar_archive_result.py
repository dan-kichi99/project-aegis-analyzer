from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class TarArchiveEntry:
    """TAR/GZIPアーカイブ内の安全な通常ファイル1件分の要約。"""

    name: str
    size: int
    extension: str
    important: bool


@dataclass(slots=True, frozen=True)
class TarArchiveResult:
    """TAR/GZIPアーカイブの安全な静的解析結果（内部データ本体は保持しない）。"""

    entries: tuple[TarArchiveEntry, ...]
    directories: tuple[str, ...]
    dangerous_paths: tuple[str, ...]
    important_files: tuple[str, ...]
    inner_strings: tuple[str, ...]
    child_file_blocks: tuple[str, ...]
    child_files_truncated: bool
    truncated: bool
