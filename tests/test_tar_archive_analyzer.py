import gzip
import io
import tarfile
from pathlib import Path

from app.file.file_input import FileInput
from app.file.static_file_analyzer import StaticFileAnalyzer
from app.file.tar_archive_analyzer import (
    ARCHIVE_SUMMARY_PREFIX,
    TarArchiveAnalyzer,
)

_FLAG = "picoCTF{tar_import_ok}"


def _build_tar(files: dict[str, bytes], *, mode: str = "w") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode=mode) as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _archive_input(name: str, content: bytes) -> FileInput:
    return FileInput(name, Path(name), len(content), Path(name).suffix, content)


# ---------------------------------------------------------------------------
# 対応形式
# ---------------------------------------------------------------------------


def test_plain_tar_is_analyzed():
    content = _build_tar({"main.py": b"print(1)"}, mode="w")
    result = TarArchiveAnalyzer().analyze(_archive_input("chal.tar", content))
    assert result is not None
    assert any(e.name == "main.py" for e in result.entries)


def test_tar_gz_is_analyzed():
    content = _build_tar({"main.py": b"print(1)"}, mode="w:gz")
    result = TarArchiveAnalyzer().analyze(_archive_input("chal.tar.gz", content))
    assert result is not None
    assert any(e.name == "main.py" for e in result.entries)


def test_tgz_is_analyzed():
    content = _build_tar({"main.py": b"print(1)"}, mode="w:gz")
    result = TarArchiveAnalyzer().analyze(_archive_input("chal.tgz", content))
    assert result is not None
    assert any(e.name == "main.py" for e in result.entries)


def test_plain_gz_single_file_is_analyzed():
    content = gzip.compress(_FLAG.encode())
    result = TarArchiveAnalyzer().analyze(_archive_input("secret.txt.gz", content))
    assert result is not None
    assert len(result.entries) == 1
    assert result.entries[0].name == "secret.txt"


# ---------------------------------------------------------------------------
# 基本
# ---------------------------------------------------------------------------


def test_empty_archive_is_handled_safely():
    content = _build_tar({}, mode="w")
    result = TarArchiveAnalyzer().analyze(_archive_input("empty.tar", content))
    assert result is not None
    assert result.entries == ()
    assert result.truncated is False


def test_corrupt_archive_returns_none_safely():
    result = TarArchiveAnalyzer().analyze(
        _archive_input("bad.tar.gz", b"not a real archive at all")
    )
    assert result is None


def test_dangerous_path_traversal_is_rejected():
    content = _build_tar({"../evil.txt": b"escape attempt"})
    result = TarArchiveAnalyzer().analyze(_archive_input("chal.tar", content))
    assert "../evil.txt" in result.dangerous_paths
    assert not any(e.name == "../evil.txt" for e in result.entries)


def test_absolute_path_is_rejected():
    content = _build_tar({"/etc/passwd": b"root:x:0:0"})
    result = TarArchiveAnalyzer().analyze(_archive_input("chal.tar", content))
    assert "/etc/passwd" in result.dangerous_paths


def test_windows_drive_path_is_rejected():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name="C:/windows/system32/evil.dll")
        data = b"malicious"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    result = TarArchiveAnalyzer().analyze(_archive_input("chal.tar", buf.getvalue()))
    assert "C:/windows/system32/evil.dll" in result.dangerous_paths


def test_huge_entry_is_rejected_and_marked_truncated():
    content = _build_tar({"huge.bin": b"A" * 2_000_000})
    result = TarArchiveAnalyzer().analyze(_archive_input("chal.tar", content))
    assert result.truncated is True
    assert not any(e.name == "huge.bin" for e in result.entries)


def test_hundred_files_are_all_processed_and_capped():
    files = {f"file_{i}.txt": f"content {i}".encode() for i in range(150)}
    content = _build_tar(files)
    result = TarArchiveAnalyzer().analyze(_archive_input("chal.tar", content))
    assert len(result.entries) <= 100
    assert result.truncated is True


def test_directory_structure_is_recorded():
    content = _build_tar(
        {"src/app/main.py": b"x", "docs/README.md": b"y"}
    )
    result = TarArchiveAnalyzer().analyze(_archive_input("chal.tar", content))
    assert "src" in result.directories
    assert "src/app" in result.directories
    assert "docs" in result.directories


# ---------------------------------------------------------------------------
# 重要ファイル取得
# ---------------------------------------------------------------------------


def test_python_file_is_important():
    content = _build_tar({"solve.py": b"print('solved')"})
    result = TarArchiveAnalyzer().analyze(_archive_input("chal.tar", content))
    entry = next(e for e in result.entries if e.name == "solve.py")
    assert entry.important is True
    assert "solve.py" in result.important_files


def test_java_file_is_important():
    content = _build_tar({"Main.java": b"class Main {}"})
    result = TarArchiveAnalyzer().analyze(_archive_input("chal.tar", content))
    entry = next(e for e in result.entries if e.name == "Main.java")
    assert entry.important is True


def test_txt_file_is_important():
    content = _build_tar({"notes.txt": b"some notes"})
    result = TarArchiveAnalyzer().analyze(_archive_input("chal.tar", content))
    entry = next(e for e in result.entries if e.name == "notes.txt")
    assert entry.important is True


def test_flag_txt_is_important_and_flag_candidate_detected():
    content = _build_tar({"flag.txt": _FLAG.encode()})
    result = TarArchiveAnalyzer().analyze(_archive_input("chal.tar", content))
    entry = next(e for e in result.entries if e.name == "flag.txt")
    assert entry.important is True
    assert any(_FLAG in s for s in result.inner_strings)


def test_readme_is_important():
    content = _build_tar({"README": b"read this"})
    result = TarArchiveAnalyzer().analyze(_archive_input("chal.tar", content))
    entry = next(e for e in result.entries if e.name == "README")
    assert entry.important is True


def test_ordinary_binary_file_is_not_important():
    content = _build_tar({"data.bin": b"\x00\x01\x02\x03"})
    result = TarArchiveAnalyzer().analyze(_archive_input("chal.tar", content))
    entry = next(e for e in result.entries if e.name == "data.bin")
    assert entry.important is False


# ---------------------------------------------------------------------------
# 既存パイプラインへの統合
# ---------------------------------------------------------------------------


def test_inner_files_are_analyzed_through_static_file_analyzer():
    inner_pe = b"MZ" + b"\x00" * 100
    content = _build_tar({"payload.exe": inner_pe, "flag.txt": _FLAG.encode()})
    result = TarArchiveAnalyzer().analyze(_archive_input("chal.tar", content))
    assert result is not None
    assert any(_FLAG in s for s in result.inner_strings)


def test_static_file_analyzer_adds_reserved_archive_summary_strings():
    content = _build_tar({"flag.txt": _FLAG.encode()}, mode="w:gz")
    file_input = FileInput(
        "chal.tar.gz", Path("chal.tar.gz"), len(content), ".gz", content
    )
    result = StaticFileAnalyzer().analyze(file_input)

    summary_strings = [s for s in result.strings if s.startswith(ARCHIVE_SUMMARY_PREFIX)]
    assert any("Archive Analysis" in s for s in summary_strings)
    assert any(_FLAG in s for s in summary_strings)


def test_tar_flag_is_solved_via_existing_strings_fast_path(tmp_path: Path):
    from unittest.mock import MagicMock

    from app.challenge.challenge_service import ChallengeService

    content = _build_tar({"flag.txt": _FLAG.encode()}, mode="w:gz")
    archive_path = tmp_path / "chal.tar.gz"
    archive_path.write_bytes(content)

    controller = MagicMock()
    analyzer = MagicMock()
    analyzer.analyze.return_value = "Forensics"
    service = ChallengeService(controller=controller, analyzer=analyzer)

    result = service.solve("tarを解析してください", [archive_path])

    assert result.flag == _FLAG
    assert result.confidence == 90
    controller.process_challenge.assert_not_called()


def test_context_builder_shows_archive_summary_without_editing_context_builder():
    from app.challenge.challenge_context_builder import ChallengeContextBuilder
    from app.challenge.challenge_input import ChallengeInput

    content = _build_tar({"flag.txt": _FLAG.encode()})
    file_input = FileInput("chal.tar", Path("chal.tar"), len(content), ".tar", content)
    file_result = StaticFileAnalyzer().analyze(file_input)
    challenge = ChallengeInput(question="解析してください", files=[file_result])

    context = ChallengeContextBuilder().build(challenge)

    assert "Archive Summary:" in context
    assert "Archive Analysis" in context


def test_existing_dto_and_public_api_are_unchanged():
    from app.file.file_analysis_result import FileAnalysisResult

    result = FileAnalysisResult("x", 0, ".bin", "unknown", None, [])
    assert result.recursive_encoding_result is None

    import inspect

    analyzer = StaticFileAnalyzer()
    signature = inspect.signature(analyzer.analyze)
    assert list(signature.parameters) == ["file_input"]


def test_no_forbidden_extraction_or_external_tools_in_source():
    source = Path("app/file/tar_archive_analyzer.py").read_text(encoding="utf-8")
    assert ".extractall(" not in source
    for forbidden in (
        "subprocess",
        "os.system",
        "eval(",
        "exec(",
        "shell=True",
        "tempfile",
        "NamedTemporaryFile",
    ):
        assert forbidden not in source
