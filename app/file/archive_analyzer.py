import io
import zipfile
from pathlib import PurePosixPath, PureWindowsPath

from app.file.archive_result import ArchiveEntry, ArchiveResult

MAX_ARCHIVE_FILES = 100
MAX_ARCHIVE_SIZE = 50_000_000
_INTERESTING = (
    "readme", "flag.txt", "password", "secret", "key", "hint",
    "writeup", "source", "main.py", "main.java", "flag",
)


class ArchiveAnalyzer:
    """Read bounded ZIP central-directory metadata without extracting entries."""

    def analyze(self, content: bytes) -> ArchiveResult | None:
        if not content or len(content) > MAX_ARCHIVE_SIZE:
            return None
        entries: list[ArchiveEntry] = []
        directories: list[str] = []
        seen_directories: set[str] = set()
        total_size = 0
        total_compressed = 0
        encrypted = 0
        truncated = False
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                archive_comment = self._decode(archive.comment)
                file_count = 0
                for info in archive.infolist():
                    if not self._safe_path(info.orig_filename):
                        continue
                    self._add_directories(
                        info.filename, directories, seen_directories
                    )
                    if info.is_dir():
                        continue
                    if file_count >= MAX_ARCHIVE_FILES:
                        truncated = True
                        break
                    if total_size + info.file_size > MAX_ARCHIVE_SIZE:
                        truncated = True
                        continue
                    file_count += 1
                    total_size += info.file_size
                    total_compressed += info.compress_size
                    is_encrypted = bool(info.flag_bits & 0x1)
                    encrypted += int(is_encrypted)
                    ratio = (
                        info.file_size / info.compress_size
                        if info.compress_size
                        else None
                    )
                    entries.append(
                        ArchiveEntry(
                            path=info.filename,
                            is_directory=False,
                            size=info.file_size,
                            compressed_size=info.compress_size,
                            compression_ratio=ratio,
                            crc=info.CRC,
                            modified_at=info.date_time,
                            comment=self._decode(info.comment),
                            encrypted=is_encrypted,
                            interesting=self._interesting(info.filename),
                        )
                    )
        except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile):
            return None
        return ArchiveResult(
            entries=tuple(entries),
            directories=tuple(directories),
            archive_comment=archive_comment,
            total_size=total_size,
            total_compressed_size=total_compressed,
            encrypted_entries=encrypted,
            truncated=truncated,
        )

    @staticmethod
    def _safe_path(filename: str) -> bool:
        if not filename or "\\" in filename:
            return False
        posix = PurePosixPath(filename)
        windows = PureWindowsPath(filename)
        return (
            not posix.is_absolute()
            and not windows.is_absolute()
            and not windows.drive
            and ".." not in posix.parts
        )

    @staticmethod
    def _add_directories(filename, directories, seen):
        parts = PurePosixPath(filename).parts
        end = len(parts) if filename.endswith("/") else len(parts) - 1
        for index in range(1, end + 1):
            directory = "/".join(parts[:index]) + "/"
            if directory not in seen:
                seen.add(directory)
                directories.append(directory)

    @staticmethod
    def _interesting(filename: str) -> bool:
        lowered = PurePosixPath(filename).name.casefold()
        return any(marker in lowered for marker in _INTERESTING)

    @staticmethod
    def _decode(value: bytes) -> str | None:
        if not value:
            return None
        return value.decode("utf-8", errors="replace")[:500]


def archive_summary_strings(result: ArchiveResult) -> list[str]:
    values = [
        (
            "[ARCHIVE_SUMMARY] "
            f"files={len(result.entries)} directories={len(result.directories)} "
            f"total_size={result.total_size} compressed={result.total_compressed_size} "
            f"encrypted={result.encrypted_entries} truncated={result.truncated}"
        )
    ]
    if result.archive_comment:
        values.append(f"[ARCHIVE_SUMMARY] comment={result.archive_comment}")
    for entry in result.entries:
        ratio = "unknown" if entry.compression_ratio is None else f"{entry.compression_ratio:.2f}"
        marker = " interesting" if entry.interesting else ""
        values.append(
            "[ARCHIVE_SUMMARY] "
            f"path={entry.path} size={entry.size} compressed={entry.compressed_size} "
            f"ratio={ratio} crc={entry.crc:08X} encrypted={entry.encrypted}{marker}"
        )
    return values
