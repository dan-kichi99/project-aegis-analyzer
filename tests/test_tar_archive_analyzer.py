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


# ---------------------------------------------------------------------------
# TASK-137B: Archive Child Content Context Bridge
# ---------------------------------------------------------------------------


def _build_context(files: dict[str, bytes], *, archive_name: str = "chal.tar") -> str:
    from app.challenge.challenge_context_builder import ChallengeContextBuilder
    from app.challenge.challenge_input import ChallengeInput

    content = _build_tar(files)
    file_input = _archive_input(archive_name, content)
    file_result = StaticFileAnalyzer().analyze(file_input)
    challenge = ChallengeInput(question="解析してください", files=[file_result])
    return ChallengeContextBuilder().build(challenge)


def test_chal_py_body_is_shown_in_context():
    context = _build_context({"substance/chal.py": b"print('hello from chal.py')"})
    assert "Archive Child Files:" in context
    assert "===== FILE: substance/chal.py =====" in context
    assert "print('hello from chal.py')" in context
    assert "===== END FILE =====" in context


def test_output_txt_body_is_shown_in_context():
    context = _build_context({"substance/output.txt": b"the ciphertext is 12345"})
    assert "===== FILE: substance/output.txt =====" in context
    assert "the ciphertext is 12345" in context


def test_path_and_body_correspondence_is_maintained():
    context = _build_context(
        {
            "a/one.py": b"BODY_ONE_UNIQUE_MARKER",
            "b/two.txt": b"BODY_TWO_UNIQUE_MARKER",
        }
    )
    one_index = context.index("===== FILE: a/one.py =====")
    one_end_index = context.index("===== END FILE =====", one_index)
    one_section = context[one_index:one_end_index]
    assert "BODY_ONE_UNIQUE_MARKER" in one_section
    assert "BODY_TWO_UNIQUE_MARKER" not in one_section

    two_index = context.index("===== FILE: b/two.txt =====")
    two_end_index = context.index("===== END FILE =====", two_index)
    two_section = context[two_index:two_end_index]
    assert "BODY_TWO_UNIQUE_MARKER" in two_section
    assert "BODY_ONE_UNIQUE_MARKER" not in two_section


def test_input_order_is_preserved_in_context():
    context = _build_context(
        {
            "z_first.py": b"first body",
            "a_second.py": b"second body",
        }
    )
    first_index = context.index("z_first.py")
    second_index = context.index("a_second.py")
    assert first_index < second_index


def test_max_ten_files_are_shared():
    files = {f"file_{i}.py": f"body {i}".encode() for i in range(15)}
    content = _build_tar(files)
    result = TarArchiveAnalyzer().analyze(_archive_input("chal.tar", content))
    assert len(result.child_file_blocks) <= 10
    assert result.child_files_truncated is True


def _extract_body(block: str) -> str:
    body = block.split("content:\n", 1)[1]
    return body.removesuffix("\n" + "[ARCHIVE_CHILD_FILE_END]")


def test_single_file_twenty_thousand_char_limit():
    huge_body = ("A" * 25_000).encode()
    content = _build_tar({"huge.py": huge_body})
    result = TarArchiveAnalyzer().analyze(_archive_input("chal.tar", content))
    body = _extract_body(result.child_file_blocks[0])
    assert len(body) == 20_000
    assert result.child_files_truncated is True


def test_total_fifty_thousand_char_limit():
    files = {f"f{i}.py": ("B" * 15_000).encode() for i in range(5)}
    content = _build_tar(files)
    result = TarArchiveAnalyzer().analyze(_archive_input("chal.tar", content))
    total_body_chars = sum(
        len(_extract_body(block)) for block in result.child_file_blocks
    )
    assert total_body_chars <= 50_000
    assert result.child_files_truncated is True


def test_truncated_is_explicitly_shown_in_context():
    files = {f"f{i}.py": ("B" * 15_000).encode() for i in range(5)}
    context = _build_context(files)
    assert "[一部の子ファイルは上限により省略されました]" in context


def test_binary_content_is_excluded_from_child_files():
    binary_body = bytes(range(256)) * 5
    content = _build_tar({"data.py": binary_body})
    result = TarArchiveAnalyzer().analyze(_archive_input("chal.tar", content))
    assert result.child_file_blocks == ()


def test_dangerous_path_is_excluded_from_child_files():
    content = _build_tar({"../evil.py": b"import os; os.system('bad')"})
    result = TarArchiveAnalyzer().analyze(_archive_input("chal.tar", content))
    assert result.child_file_blocks == ()
    assert "../evil.py" in result.dangerous_paths


def test_child_file_blocks_do_not_duplicate_in_normal_strings_section():
    context = _build_context({"substance/chal.py": b"UNIQUE_BODY_TOKEN_XYZ"})
    strings_heading_index = context.index("抽出文字列：")
    child_heading_index = context.index("Archive Child Files:")
    plain_strings_block = context[strings_heading_index:child_heading_index]
    assert "[ARCHIVE_CHILD_FILE_BEGIN]" not in plain_strings_block


def test_archive_summary_heading_still_present_alongside_child_files():
    context = _build_context({"substance/chal.py": b"x = 1"})
    assert "Archive Summary:" in context
    assert "Archive Child Files:" in context
    assert context.index("Archive Summary:") < context.index("Archive Child Files:")


def test_zip_png_pdf_jpeg_wav_regression_are_unaffected():
    zip_content = b"PK\x05\x06" + b"\x00" * 18
    zip_input = FileInput("empty.zip", Path("empty.zip"), len(zip_content), ".zip", zip_content)
    zip_result = StaticFileAnalyzer().analyze(zip_input)
    assert zip_result.detected_type == "zip"

    png_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    png_input = FileInput("chal.png", Path("chal.png"), len(png_content), ".png", png_content)
    png_result = StaticFileAnalyzer().analyze(png_input)
    assert png_result.detected_type == "png"

    pdf_content = b"%PDF-1.7\n1 0 obj\n<< >>\nendobj\ntrailer\n<< >>\n%%EOF\n"
    pdf_input = FileInput("chal.pdf", Path("chal.pdf"), len(pdf_content), ".pdf", pdf_content)
    pdf_result = StaticFileAnalyzer().analyze(pdf_input)
    assert pdf_result.detected_type == "pdf"

    jpeg_content = b"\xff\xd8\xff\xd9"
    jpeg_input = FileInput("chal.jpg", Path("chal.jpg"), len(jpeg_content), ".jpg", jpeg_content)
    jpeg_result = StaticFileAnalyzer().analyze(jpeg_input)
    assert jpeg_result.detected_type == "jpeg"

    wav_content = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt "
    wav_input = FileInput("chal.wav", Path("chal.wav"), len(wav_content), ".wav", wav_content)
    wav_result = StaticFileAnalyzer().analyze(wav_input)
    assert wav_result.name == "chal.wav"


def test_challenge_service_and_public_dto_are_unchanged():
    import inspect

    from app.challenge.challenge_service import ChallengeService
    from app.file.file_analysis_result import FileAnalysisResult

    result = FileAnalysisResult("x", 0, ".bin", "unknown", None, [])
    assert result.recursive_encoding_result is None

    signature = inspect.signature(ChallengeService.__init__)
    assert list(signature.parameters) == [
        "self",
        "controller",
        "analyzer",
        "file_loader",
        "file_analyzer",
        "event_publisher",
    ]


# -- 実データ相当テスト -------------------------------------------------------


def test_substance_style_flag_multiplication_expressions_are_readable_in_context():
    chal_py = (
        b"from Crypto.Util.number import *\n"
        b"x = flag * a * b * c\n"
        b"y = flag * d * e * f\n"
    )
    context = _build_context({"substance/chal.py": chal_py})
    assert "x = flag * a * b * c" in context
    assert "y = flag * d * e * f" in context


def test_square_rsa_style_n_equals_p_times_p_is_readable_in_context():
    chall_py = b"n = p * p\nc = pow(m, e, n)\n"
    context = _build_context({"square-rsa/chall.py": chall_py})
    assert "n = p * p" in context


def test_encoding_basics_style_chall_py_and_chall_txt_both_reach_context():
    chall_py = b"print(open('chall.txt').read())\n"
    chall_txt = b"encoded_flag = base64.b64encode(FLAG)\n"
    context = _build_context(
        {
            "encoding-basics/chall.py": chall_py,
            "encoding-basics/chall.txt": chall_txt,
        }
    )
    assert "print(open('chall.txt').read())" in context
    assert "encoded_flag = base64.b64encode(FLAG)" in context
