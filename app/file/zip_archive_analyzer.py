import io
import stat
import zipfile
from pathlib import PurePosixPath, PureWindowsPath

from app.file.file_analysis_result import FileAnalysisResult
from app.file.file_input import FileInput
from app.file.static_file_analyzer import StaticFileAnalyzer

_MAX_ENTRIES = 50
_MAX_ENTRY_SIZE = 2_000_000
_MAX_TOTAL_SIZE = 10_000_000
_MAX_COMPRESSION_RATIO = 100


class ZipArchiveAnalyzer:
    """ZIP内の安全な通常ファイルをメモリ上で静的解析する。"""

    def __init__(self, file_analyzer: StaticFileAnalyzer) -> None:
        self._file_analyzer = file_analyzer

    def analyze(self, archive_input: FileInput) -> list[FileAnalysisResult]:
        results: list[FileAnalysisResult] = []
        total_size = 0

        try:
            with zipfile.ZipFile(io.BytesIO(archive_input.content)) as archive:
                for info in archive.infolist():
                    if len(results) >= _MAX_ENTRIES:
                        break
                    if not self._is_safe_entry(info):
                        continue
                    if total_size + info.file_size > _MAX_TOTAL_SIZE:
                        continue

                    content = self._read_entry(archive, info)
                    if content is None:
                        continue

                    total_size += len(content)
                    entry_name = f"{archive_input.name}::{info.filename}"
                    entry_path = PurePosixPath(info.filename)
                    file_input = FileInput(
                        name=entry_name,
                        path=archive_input.path,
                        size=len(content),
                        extension=entry_path.suffix,
                        content=content,
                    )
                    results.append(self._file_analyzer.analyze(file_input))
        except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile):
            return []

        return results

    def _is_safe_entry(self, info: zipfile.ZipInfo) -> bool:
        if info.is_dir() or info.flag_bits & 0x1:
            return False
        if not self._is_safe_path(info.orig_filename):
            return False
        if self._is_special_file(info):
            return False
        if info.file_size > _MAX_ENTRY_SIZE or info.compress_size == 0:
            return False

        compression_ratio = info.file_size / info.compress_size
        return compression_ratio <= _MAX_COMPRESSION_RATIO

    def _is_safe_path(self, filename: str) -> bool:
        if not filename or "\\" in filename:
            return False

        posix_path = PurePosixPath(filename)
        windows_path = PureWindowsPath(filename)
        return (
            not posix_path.is_absolute()
            and not windows_path.is_absolute()
            and not windows_path.drive
            and ".." not in posix_path.parts
        )

    def _is_special_file(self, info: zipfile.ZipInfo) -> bool:
        mode = info.external_attr >> 16
        file_type = stat.S_IFMT(mode)
        return file_type not in (0, stat.S_IFREG)

    def _read_entry(
        self,
        archive: zipfile.ZipFile,
        info: zipfile.ZipInfo,
    ) -> bytes | None:
        try:
            with archive.open(info) as entry:
                content = entry.read(_MAX_ENTRY_SIZE + 1)
        except (OSError, RuntimeError, zipfile.BadZipFile):
            return None

        if len(content) > _MAX_ENTRY_SIZE:
            return None
        return content
