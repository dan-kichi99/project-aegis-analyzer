import io
import stat
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

from app.analyzer.analyzer import Analyzer
from app.challenge.challenge_service import ChallengeService
from app.file.file_input import FileInput
from app.file.file_loader import FileLoader
from app.file.static_file_analyzer import StaticFileAnalyzer
from app.file.zip_archive_analyzer import ZipArchiveAnalyzer


def make_zip_bytes(
    entries: list[tuple[str, bytes]],
    compression: int = zipfile.ZIP_DEFLATED,
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return output.getvalue()


def make_archive_input(content: bytes, name: str = "archive.zip") -> FileInput:
    return FileInput(
        name=name,
        path=Path(name),
        size=len(content),
        extension=".zip",
        content=content,
    )


def analyze_zip(content: bytes):
    return ZipArchiveAnalyzer(StaticFileAnalyzer()).analyze(
        make_archive_input(content)
    )


def make_service() -> tuple[ChallengeService, MagicMock]:
    analyzer = MagicMock(spec=Analyzer)
    analyzer.analyze.return_value = "Misc"
    controller = MagicMock()
    service = ChallengeService(
        controller=controller,
        analyzer=analyzer,
        file_loader=FileLoader(),
        file_analyzer=StaticFileAnalyzer(),
    )
    return service, controller


def test_analyzes_text_file_inside_zip():
    results = analyze_zip(make_zip_bytes([("notes/secret.txt", b"hello")]))

    assert len(results) == 1
    assert results[0].text_content == "hello"
    assert "hello" in results[0].strings


def test_preserves_archive_and_entry_names():
    results = analyze_zip(make_zip_bytes([("bin/challenge.exe", b"MZdata")]))

    assert results[0].name == "archive.zip::bin/challenge.exe"
    assert results[0].extension == ".exe"


def test_zip_flag_uses_existing_fast_path_without_ai(tmp_path: Path):
    archive_path = tmp_path / "flag.zip"
    archive_path.write_bytes(
        make_zip_bytes([("secret.txt", b"FLAG{zip_flag}")])
    )
    service, controller = make_service()

    result = service.solve("Analyze ZIP", [archive_path])

    assert result.flag == "FLAG{zip_flag}"
    assert "flag.zip::secret.txt" in result.reason
    controller.process_challenge.assert_not_called()
    controller.ai_client.generate.assert_not_called()


def test_zip_base64_flag_uses_existing_decoder(tmp_path: Path):
    archive_path = tmp_path / "base64.zip"
    archive_path.write_bytes(
        make_zip_bytes(
            [("encoded.txt", b"RkxBR3t6aXBfYmFzZTY0fQ==")]
        )
    )
    service, controller = make_service()

    result = service.solve("Analyze ZIP", [archive_path])

    assert result.flag == "FLAG{zip_base64}"
    controller.process_challenge.assert_not_called()


def test_zip_hex_flag_uses_existing_decoder(tmp_path: Path):
    archive_path = tmp_path / "hex.zip"
    archive_path.write_bytes(
        make_zip_bytes(
            [("encoded.txt", b"464c41477b7a69705f6865787d")]
        )
    )
    service, controller = make_service()

    result = service.solve("Analyze ZIP", [archive_path])

    assert result.flag == "FLAG{zip_hex}"
    controller.ai_client.generate.assert_not_called()


def test_ignores_directory_entries():
    content = make_zip_bytes([("folder/", b""), ("folder/file.txt", b"ok")])

    results = analyze_zip(content)

    assert [result.name for result in results] == [
        "archive.zip::folder/file.txt"
    ]


def test_ignores_parent_traversal_path():
    results = analyze_zip(make_zip_bytes([("../evil.txt", b"evil")]))

    assert results == []


def test_ignores_absolute_and_drive_paths():
    content = make_zip_bytes(
        [("/evil.txt", b"one"), ("C:/evil.txt", b"two")]
    )

    assert analyze_zip(content) == []


def test_ignores_backslash_path():
    content = make_zip_bytes([("folder/evil.txt", b"evil")])
    content = content.replace(b"folder/evil.txt", b"folder\\evil.txt")
    results = analyze_zip(content)

    assert results == []


def test_limits_entry_count_to_fifty():
    entries = [(f"file-{index}.txt", b"data") for index in range(55)]

    results = analyze_zip(make_zip_bytes(entries, zipfile.ZIP_STORED))

    assert len(results) == 50


def test_ignores_entry_larger_than_two_megabytes():
    content = make_zip_bytes(
        [("large.bin", b"A" * 2_000_001)],
        zipfile.ZIP_STORED,
    )

    assert analyze_zip(content) == []


def test_limits_total_uncompressed_size_to_ten_megabytes():
    entries = [
        (f"part-{index}.bin", bytes([index]) * 2_000_000)
        for index in range(6)
    ]

    results = analyze_zip(make_zip_bytes(entries, zipfile.ZIP_STORED))

    assert len(results) == 5


def test_ignores_extreme_compression_ratio():
    content = make_zip_bytes([("bomb.txt", b"A" * 1_000_000)])

    assert analyze_zip(content) == []


def test_ignores_symlink_entry():
    output = io.BytesIO()
    link_info = zipfile.ZipInfo("link.txt")
    link_info.create_system = 3
    link_info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(link_info, b"target.txt")

    assert analyze_zip(output.getvalue()) == []


def test_encrypted_entry_flag_is_rejected():
    info = zipfile.ZipInfo("secret.txt")
    info.flag_bits = 0x1
    info.file_size = 4
    info.compress_size = 4
    analyzer = ZipArchiveAnalyzer(StaticFileAnalyzer())

    assert analyzer._is_safe_entry(info) is False


def test_broken_zip_returns_no_entries():
    assert analyze_zip(b"PK\x03\x04broken") == []


def test_nested_zip_is_not_recursively_expanded():
    nested = make_zip_bytes([("deep.txt", b"FLAG{nested}")])
    outer = make_zip_bytes([("nested.zip", nested)])

    results = analyze_zip(outer)

    assert [result.name for result in results] == [
        "archive.zip::nested.zip"
    ]
    assert all("::nested.zip::" not in result.name for result in results)


def test_challenge_keeps_original_zip_analysis_result(tmp_path: Path):
    archive_path = tmp_path / "plain.zip"
    archive_path.write_bytes(make_zip_bytes([("notes.txt", b"no answer")]))
    service, controller = make_service()
    expected = object()
    captured_files = []

    def capture_challenge(challenge):
        captured_files.extend(challenge.files)
        return expected

    controller.process_challenge.side_effect = capture_challenge

    result = service.solve("Analyze ZIP", [archive_path])

    assert result is expected
    assert [file_result.name for file_result in captured_files] == [
        "plain.zip",
        "plain.zip::notes.txt",
    ]


def test_non_zip_static_analysis_is_unchanged():
    content = b"ordinary text"
    file_input = FileInput(
        name="plain.txt",
        path=Path("plain.txt"),
        size=len(content),
        extension=".txt",
        content=content,
    )

    result = StaticFileAnalyzer().analyze(file_input)

    assert result.detected_type == "text"
    assert result.text_content == "ordinary text"
    assert "ordinary text" in result.strings
