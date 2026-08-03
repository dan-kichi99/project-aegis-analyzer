import gzip
import io
import tarfile
from pathlib import PurePosixPath, PureWindowsPath

from app.file.file_analysis_result import FileAnalysisResult
from app.file.file_input import FileInput
from app.file.static_file_analyzer import StaticFileAnalyzer
from app.file.tar_archive_result import TarArchiveEntry, TarArchiveResult
from app.judge.flag_extractor import FlagExtractor

_MAX_ENTRIES = 100
_MAX_ENTRY_SIZE = 1_000_000
_MAX_TOTAL_SIZE = 50_000_000
_MAX_INNER_STRING_LINES = 50
_MAX_NESTING_DEPTH = 1

CHILD_FILE_BEGIN = "[ARCHIVE_CHILD_FILE_BEGIN]"
CHILD_FILE_END = "[ARCHIVE_CHILD_FILE_END]"
_MAX_CHILD_FILES = 10
_MAX_CHILD_FILE_CHARS = 20_000
_MAX_CHILD_TOTAL_CHARS = 50_000
_BINARY_LOOK_SAMPLE = 2_000
_BINARY_CONTROL_RATIO = 0.01

_TEXT_CHILD_TYPES = {
    ".py": "python",
    ".java": "java",
    ".c": "c",
    ".h": "c-header",
    ".cpp": "cpp",
    ".hpp": "cpp-header",
    ".rs": "rust",
    ".go": "go",
    ".js": "javascript",
    ".ts": "typescript",
    ".php": "php",
    ".rb": "ruby",
    ".cs": "csharp",
    ".txt": "text",
    ".md": "markdown",
    ".json": "json",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".cfg": "config",
    ".ini": "config",
}

_IMPORTANT_EXTENSIONS = frozenset(
    {
        ".py",
        ".java",
        ".txt",
        ".md",
        ".json",
        ".xml",
        ".yaml",
        ".yml",
        ".cfg",
        ".ini",
        ".pem",
        ".key",
    }
)
_IMPORTANT_NAME_MARKERS = (
    "flag",
    "secret",
    "password",
    "hint",
    "readme",
    "writeup",
    "source",
)

ARCHIVE_SUMMARY_PREFIX = "[ARCHIVE_SUMMARY] "


def tar_archive_summary_strings(result: TarArchiveResult) -> list[str]:
    """TarArchiveResultを既存の[ARCHIVE_SUMMARY]規約に沿ったsummary文字列へ変換する。"""
    summary_line = (
        f"{ARCHIVE_SUMMARY_PREFIX}Archive Analysis "
        f"files={len(result.entries)} directories={len(result.directories)} "
        f"important={len(result.important_files)} dangerous={len(result.dangerous_paths)}"
    )
    values = [summary_line]
    for entry in result.entries:
        marker = " important" if entry.important else ""
        values.append(
            f"{ARCHIVE_SUMMARY_PREFIX}path={entry.name} size={entry.size}{marker}"
        )
    for path in result.dangerous_paths:
        values.append(f"{ARCHIVE_SUMMARY_PREFIX}dangerous_path={path}")
    for value in result.inner_strings:
        values.append(f"{ARCHIVE_SUMMARY_PREFIX}{value}")
    return values


CHILD_FILES_TRUNCATED_MARKER = "[ARCHIVE_CHILD_FILES_TRUNCATED]"


def tar_archive_child_file_strings(result: TarArchiveResult) -> list[str]:
    """子ファイル本文ブロックを、Archive Summaryとは別系統のstringsとして返す。"""
    values = list(result.child_file_blocks)
    if result.child_files_truncated:
        values.append(CHILD_FILES_TRUNCATED_MARKER)
    return values


class _ChildContentState:
    """アーカイブ全体を通した子ファイル本文の収集状態（件数・合計文字数・重複）。"""

    def __init__(self) -> None:
        self.blocks: list[str] = []
        self.seen_paths: set[str] = set()
        self.total_chars = 0
        self.truncated = False


class TarArchiveAnalyzer:
    """TAR/GZIP内の安全な通常ファイルをメモリ上で既存パイプラインへ流す。"""

    def __init__(
        self,
        file_analyzer: StaticFileAnalyzer | None = None,
        flag_extractor: FlagExtractor | None = None,
    ) -> None:
        self._file_analyzer = file_analyzer or StaticFileAnalyzer()
        self._flag_extractor = flag_extractor or FlagExtractor()
        self._depth = 0

    def analyze(self, archive_input: FileInput) -> TarArchiveResult | None:
        if not archive_input.content or len(archive_input.content) > _MAX_TOTAL_SIZE:
            return None
        if self._depth >= _MAX_NESTING_DEPTH:
            # tar-in-tar等の再帰展開による無限再帰を防止する。
            return None

        self._depth += 1
        try:
            return self._analyze_content(archive_input)
        finally:
            self._depth -= 1

    def _analyze_content(self, archive_input: FileInput) -> TarArchiveResult | None:
        try:
            with tarfile.open(
                fileobj=io.BytesIO(archive_input.content), mode="r:*"
            ) as archive:
                members = archive.getmembers()
                return self._analyze_members(archive_input, archive, members)
        except (OSError, tarfile.TarError, EOFError, ValueError):
            return self._analyze_plain_gzip(archive_input)

    # -- tar (plain / gzip-compressed) --------------------------------------

    def _analyze_members(
        self,
        archive_input: FileInput,
        archive: tarfile.TarFile,
        members: list[tarfile.TarInfo],
    ) -> TarArchiveResult:
        entries: list[TarArchiveEntry] = []
        directories: list[str] = []
        seen_directories: set[str] = set()
        dangerous_paths: list[str] = []
        important_files: list[str] = []
        inner_strings: list[str] = []
        child_state = _ChildContentState()
        total_size = 0
        truncated = False

        try:
            for member in members:
                if not self._is_safe_path(member.name):
                    dangerous_paths.append(member.name)
                    continue
                self._record_directories(
                    member.name,
                    directories,
                    seen_directories,
                    is_directory=member.isdir(),
                )

                if member.isdir():
                    continue
                if not member.isfile():
                    continue
                if len(entries) >= _MAX_ENTRIES:
                    truncated = True
                    break
                if member.size > _MAX_ENTRY_SIZE:
                    truncated = True
                    continue
                if total_size + member.size > _MAX_TOTAL_SIZE:
                    truncated = True
                    continue

                content = self._read_member(archive, member)
                if content is None:
                    continue
                total_size += len(content)

                important = self._is_important(member.name)
                if important:
                    important_files.append(member.name)
                entries.append(
                    TarArchiveEntry(
                        name=member.name,
                        size=member.size,
                        extension=PurePosixPath(member.name).suffix,
                        important=important,
                    )
                )

                result = self._analyze_inner_file(
                    archive_input, member.name, content, inner_strings
                )
                self._maybe_capture_child_content(
                    member.name, content, result, child_state
                )
        except (OSError, tarfile.TarError, EOFError):
            truncated = True

        return TarArchiveResult(
            entries=tuple(entries),
            directories=tuple(directories),
            dangerous_paths=tuple(dangerous_paths),
            important_files=tuple(important_files),
            inner_strings=tuple(inner_strings[:_MAX_INNER_STRING_LINES]),
            child_file_blocks=tuple(child_state.blocks),
            child_files_truncated=child_state.truncated,
            truncated=truncated,
        )

    def _read_member(
        self, archive: tarfile.TarFile, member: tarfile.TarInfo
    ) -> bytes | None:
        try:
            extracted = archive.extractfile(member)
            if extracted is None:
                return None
            content = extracted.read(_MAX_ENTRY_SIZE + 1)
        except (OSError, tarfile.TarError):
            return None
        if len(content) > _MAX_ENTRY_SIZE:
            return None
        return content

    # -- plain (non-tar) gzip single file ------------------------------------

    def _analyze_plain_gzip(self, archive_input: FileInput) -> TarArchiveResult | None:
        try:
            content = gzip.decompress(archive_input.content)
        except (OSError, gzip.BadGzipFile, EOFError):
            return None

        truncated = len(content) > _MAX_ENTRY_SIZE
        content = content[:_MAX_ENTRY_SIZE]
        inner_name = archive_input.name
        for suffix in (".tgz", ".tar.gz", ".gz"):
            if inner_name.lower().endswith(suffix):
                inner_name = inner_name[: -len(suffix)] or "file"
                break

        important = self._is_important(inner_name)
        entry = TarArchiveEntry(
            name=inner_name,
            size=len(content),
            extension=PurePosixPath(inner_name).suffix,
            important=important,
        )
        inner_strings: list[str] = []
        child_state = _ChildContentState()
        result = self._analyze_inner_file(
            archive_input, inner_name, content, inner_strings
        )
        self._maybe_capture_child_content(inner_name, content, result, child_state)

        return TarArchiveResult(
            entries=(entry,),
            directories=(),
            dangerous_paths=(),
            important_files=(inner_name,) if important else (),
            inner_strings=tuple(inner_strings[:_MAX_INNER_STRING_LINES]),
            child_file_blocks=tuple(child_state.blocks),
            child_files_truncated=child_state.truncated,
            truncated=truncated,
        )

    # -- inner file pipeline --------------------------------------------------

    def _analyze_inner_file(
        self,
        archive_input: FileInput,
        entry_name: str,
        content: bytes,
        inner_strings: list[str],
    ) -> FileAnalysisResult:
        entry_path = PurePosixPath(entry_name)
        file_input = FileInput(
            name=f"{archive_input.name}::{entry_name}",
            path=archive_input.path,
            size=len(content),
            extension=entry_path.suffix,
            content=content,
        )
        result = self._file_analyzer.analyze(file_input)

        candidates = list(result.strings)
        if result.text_content is not None:
            candidates.append(result.text_content)
        seen_flags: set[str] = set()
        for candidate in candidates:
            for flag in self._flag_extractor.extract_all(candidate):
                if flag not in seen_flags:
                    seen_flags.add(flag)
                    inner_strings.append(f"flag_candidate={entry_name}:{flag}")
        return result

    # -- child file content (Agent context bridge) ---------------------------

    def _maybe_capture_child_content(
        self,
        entry_name: str,
        content: bytes,
        result: FileAnalysisResult,
        state: _ChildContentState,
    ) -> None:
        type_label = _TEXT_CHILD_TYPES.get(PurePosixPath(entry_name).suffix.lower())
        if type_label is None:
            return
        if entry_name in state.seen_paths:
            return
        if len(state.blocks) >= _MAX_CHILD_FILES:
            state.truncated = True
            return
        if state.total_chars >= _MAX_CHILD_TOTAL_CHARS:
            state.truncated = True
            return
        if b"\x00" in content:
            return

        text = result.text_content
        if text is None:
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                return
        if not text or self._looks_binary(text):
            return

        state.seen_paths.add(entry_name)

        limited = text[:_MAX_CHILD_FILE_CHARS]
        file_truncated = len(text) > _MAX_CHILD_FILE_CHARS
        remaining_total = _MAX_CHILD_TOTAL_CHARS - state.total_chars
        if len(limited) > remaining_total:
            limited = limited[:remaining_total]
            file_truncated = True
        state.total_chars += len(limited)
        if file_truncated:
            state.truncated = True

        block = (
            f"{CHILD_FILE_BEGIN}\n"
            f"path={entry_name}\n"
            f"type={type_label}\n"
            f"size={len(content)}\n"
            "content:\n"
            f"{limited}\n"
            f"{CHILD_FILE_END}"
        )
        state.blocks.append(block)

    @staticmethod
    def _looks_binary(text: str) -> bool:
        sample = text[:_BINARY_LOOK_SAMPLE]
        if not sample:
            return False
        control_count = sum(
            1 for ch in sample if ord(ch) < 0x20 and ch not in "\n\r\t"
        )
        return (control_count / len(sample)) > _BINARY_CONTROL_RATIO

    # -- safety helpers -------------------------------------------------------

    @staticmethod
    def _is_safe_path(name: str) -> bool:
        if not name or "\\" in name:
            return False
        posix_path = PurePosixPath(name)
        windows_path = PureWindowsPath(name)
        return (
            not posix_path.is_absolute()
            and not windows_path.is_absolute()
            and not windows_path.drive
            and ".." not in posix_path.parts
        )

    @staticmethod
    def _record_directories(
        name: str,
        directories: list[str],
        seen: set[str],
        *,
        is_directory: bool,
    ) -> None:
        parts = PurePosixPath(name).parts
        upper_bound = len(parts) if is_directory else len(parts) - 1
        for depth in range(1, upper_bound + 1):
            directory = "/".join(parts[:depth])
            if directory and directory not in seen:
                seen.add(directory)
                directories.append(directory)

    @staticmethod
    def _is_important(name: str) -> bool:
        path = PurePosixPath(name)
        if path.suffix.lower() in _IMPORTANT_EXTENSIONS:
            return True
        lowered = path.name.lower()
        return any(marker in lowered for marker in _IMPORTANT_NAME_MARKERS)
