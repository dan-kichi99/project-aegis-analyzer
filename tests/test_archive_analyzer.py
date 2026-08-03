import io
import zipfile
from pathlib import Path

import pytest

from app.challenge.challenge_context_builder import ChallengeContextBuilder
from app.challenge.challenge_input import ChallengeInput
from app.file.archive_analyzer import (
    MAX_ARCHIVE_FILES,
    MAX_ARCHIVE_SIZE,
    ArchiveAnalyzer,
)
from app.file.file_input import FileInput
from app.file.static_file_analyzer import StaticFileAnalyzer


def _zip(entries=(), *, comment: bytes = b"") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.comment = comment
        for item in entries:
            if len(item) == 2:
                name, content = item
                archive.writestr(name, content)
            else:
                name, content, entry_comment = item
                info = zipfile.ZipInfo(name, date_time=(2024, 1, 2, 3, 4, 6))
                info.comment = entry_comment
                archive.writestr(info, content)
    return output.getvalue()


def _analyze(content: bytes):
    return ArchiveAnalyzer().analyze(content)


def test_lists_zip_entry_metadata_without_reading_content():
    result = _analyze(_zip([("docs/readme.txt", b"hello")]))
    assert result is not None
    entry = result.entries[0]
    assert entry.path == "docs/readme.txt"
    assert entry.size == 5
    assert entry.compressed_size > 0
    assert entry.compression_ratio is not None
    assert entry.crc != 0
    assert len(entry.modified_at) == 6
    assert entry.modified_at[0] >= 1980
    assert entry.encrypted is False


def test_empty_zip_is_valid():
    result = _analyze(_zip())
    assert result is not None
    assert result.entries == ()
    assert result.directories == ()
    assert result.total_size == 0


def test_archive_and_entry_comments_are_decoded():
    result = _analyze(_zip([("note.txt", b"x", "項目".encode())], comment="全体".encode()))
    assert result is not None
    assert result.archive_comment == "全体"
    assert result.entries[0].comment == "項目"


def test_unicode_and_nested_directory_names_are_preserved():
    result = _analyze(_zip([("資料/深層/旗.txt", b"x")]))
    assert result is not None
    assert result.entries[0].path == "資料/深層/旗.txt"
    assert result.directories == ("資料/", "資料/深層/")


def test_explicit_directory_entries_are_not_files():
    result = _analyze(_zip([("folder/", b""), ("folder/file.txt", b"x")]))
    assert result is not None
    assert len(result.entries) == 1
    assert result.directories == ("folder/",)


@pytest.mark.parametrize(
    "name",
    ["../evil.txt", "a/../../evil", "/absolute.txt", "C:/drive.txt"],
)
def test_zip_slip_and_unsafe_paths_are_excluded(name: str):
    result = _analyze(_zip([(name, b"bad"), ("safe.txt", b"ok")]))
    assert result is not None
    assert [entry.path for entry in result.entries] == ["safe.txt"]


def test_backslash_path_in_central_directory_is_excluded():
    content = _zip([("folder/evil.txt", b"bad"), ("safe.txt", b"ok")])
    content = content.replace(b"folder/evil.txt", b"folder\\evil.txt")
    result = _analyze(content)
    assert result is not None
    assert [entry.path for entry in result.entries] == ["safe.txt"]


@pytest.mark.parametrize(
    "name",
    [
        "README", "flag.txt", "password.txt", "secret.bin", "key.dat",
        "hint.md", "writeup.txt", "source.zip", "main.py", "Main.java",
        "my_flag_data.bin",
    ],
)
def test_interesting_names_are_detected_case_insensitively(name: str):
    result = _analyze(_zip([(f"nested/{name}", b"x")]))
    assert result is not None
    assert result.entries[0].interesting is True


def test_ordinary_name_is_not_marked_interesting():
    result = _analyze(_zip([("image.png", b"x")]))
    assert result is not None
    assert result.entries[0].interesting is False


def test_file_count_is_limited_to_one_hundred():
    content = _zip([(f"file-{index}.txt", b"x") for index in range(105)])
    result = _analyze(content)
    assert result is not None
    assert len(result.entries) == MAX_ARCHIVE_FILES
    assert result.truncated is True


def test_total_sizes_and_compression_ratio_are_aggregated():
    result = _analyze(_zip([("a.txt", b"A" * 100), ("b.txt", b"B" * 200)]))
    assert result is not None
    assert result.total_size == 300
    assert result.total_compressed_size == sum(item.compressed_size for item in result.entries)
    assert all(item.compression_ratio and item.compression_ratio > 1 for item in result.entries)


def test_input_larger_than_fifty_mb_is_rejected_without_parsing():
    assert _analyze(b"X" * (MAX_ARCHIVE_SIZE + 1)) is None


def test_declared_total_size_over_limit_is_skipped_safely(monkeypatch):
    info = zipfile.ZipInfo("large.bin")
    info.file_size = MAX_ARCHIVE_SIZE + 1
    info.compress_size = 1

    class FakeArchive:
        comment = b""

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def infolist(self):
            return [info]

    monkeypatch.setattr("app.file.archive_analyzer.zipfile.ZipFile", lambda _source: FakeArchive())
    result = _analyze(b"PK")
    assert result is not None
    assert result.entries == ()
    assert result.truncated is True


def test_encryption_flag_is_reported_without_decryption(monkeypatch):
    info = zipfile.ZipInfo("secret.txt")
    info.file_size = 10
    info.compress_size = 5
    info.flag_bits = 1
    info.CRC = 0

    class FakeArchive:
        comment = b""

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def infolist(self):
            return [info]

    monkeypatch.setattr("app.file.archive_analyzer.zipfile.ZipFile", lambda _source: FakeArchive())
    result = _analyze(b"PK")
    assert result is not None
    assert result.entries[0].encrypted is True
    assert result.encrypted_entries == 1


@pytest.mark.parametrize("content", [b"", b"not zip", b"PK\x03\x04broken", b"PK\x05\x06short"])
def test_empty_invalid_and_broken_archives_do_not_raise(content: bytes):
    assert _analyze(content) is None


def test_static_file_analyzer_adds_bounded_archive_summary_strings():
    content = _zip([("flag.txt", b"FLAG{x}"), ("docs/readme.md", b"read")])
    result = StaticFileAnalyzer().analyze(
        FileInput("sample.zip", Path("sample.zip"), len(content), ".zip", content)
    )
    summaries = [item for item in result.strings if item.startswith("[ARCHIVE_SUMMARY] ")]
    assert summaries
    assert any("files=2" in item for item in summaries)
    assert any("path=flag.txt" in item and "interesting" in item for item in summaries)


def test_context_builder_displays_archive_summary():
    content = _zip([("nested/Main.java", b"class Main {}")], comment=b"challenge")
    file_result = StaticFileAnalyzer().analyze(
        FileInput("source.zip", Path("source.zip"), len(content), ".zip", content)
    )
    context = ChallengeContextBuilder().build(ChallengeInput("Analyze", [file_result]))
    assert "Archive Summary:" in context
    assert "path=nested/Main.java" in context
    assert "comment=challenge" in context


def test_non_zip_static_analysis_is_backward_compatible():
    content = b"ordinary text"
    result = StaticFileAnalyzer().analyze(
        FileInput("plain.txt", Path("plain.txt"), len(content), ".txt", content)
    )
    assert result.detected_type == "text"
    assert result.text_content == "ordinary text"
    assert not any(item.startswith("[ARCHIVE_SUMMARY]") for item in result.strings)


def test_dto_is_frozen_and_analyzer_does_not_modify_input():
    content = _zip([("a.txt", b"x")])
    before = bytes(content)
    result = _analyze(content)
    assert result is not None and content == before
    with pytest.raises((AttributeError, TypeError)):
        result.entries[0].path = "changed"


def test_implementation_never_extracts_or_executes_entries():
    source = Path("app/file/archive_analyzer.py").read_text(encoding="utf-8")
    for forbidden in (
        ".extract(", ".extractall(", "subprocess", "shell=True",
        "\nexec(", "\neval(", "\ncompile(", "OpenAI", "requests",
    ):
        assert forbidden not in source
