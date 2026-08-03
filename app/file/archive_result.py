from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class ArchiveEntry:
    path: str
    is_directory: bool
    size: int
    compressed_size: int
    compression_ratio: float | None
    crc: int
    modified_at: tuple[int, int, int, int, int, int]
    comment: str | None
    encrypted: bool
    interesting: bool


@dataclass(slots=True, frozen=True)
class ArchiveResult:
    entries: tuple[ArchiveEntry, ...]
    directories: tuple[str, ...]
    archive_comment: str | None
    total_size: int
    total_compressed_size: int
    encrypted_entries: int
    truncated: bool
