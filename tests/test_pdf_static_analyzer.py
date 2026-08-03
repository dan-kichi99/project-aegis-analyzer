import base64
import inspect
import re
import zlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.challenge.challenge_context_builder import ChallengeContextBuilder
from app.challenge.challenge_input import ChallengeInput
from app.challenge.challenge_service import ChallengeService
from app.file.file_analysis_result import FileAnalysisResult
from app.file.file_input import FileInput
from app.file.pdf_static_analyzer import (
    PDF_INFO_PREFIX,
    PDF_METADATA_PREFIX,
    PDF_TRAILING_PREFIX,
    PdfStaticAnalyzer,
)
from app.file.static_file_analyzer import StaticFileAnalyzer

_FLAG = "picoCTF{pdf_static_ok}"


def _obj(number: int, generation: int, body: bytes) -> bytes:
    return f"{number} {generation} obj\n".encode("latin-1") + body + b"\nendobj\n"


def _basic_pdf(
    *,
    extra_objects: list[bytes] | None = None,
    trailer: bytes = b"<< /Root 1 0 R >>",
    footer: bytes | None = None,
) -> bytes:
    parts = [
        b"%PDF-1.7\n",
        _obj(1, 0, b"<< /Type /Catalog /Pages 2 0 R >>"),
        _obj(2, 0, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        _obj(3, 0, b"<< /Type /Page /Parent 2 0 R >>"),
    ]
    if extra_objects:
        parts.extend(extra_objects)
    if footer is None:
        footer = (
            b"xref\n0 4\n"
            b"trailer\n" + trailer + b"\n"
            b"startxref\n0\n"
            b"%%EOF\n"
        )
    parts.append(footer)
    return b"".join(parts)


# ---------------------------------------------------------------------------
# 正常系
# ---------------------------------------------------------------------------


def test_header_version_and_object_detection():
    content = _basic_pdf()
    result = PdfStaticAnalyzer().analyze(content)
    assert result.valid_header is True
    assert result.version == "1.7"
    assert result.object_count == 3
    assert [o.object_number for o in result.objects] == [1, 2, 3]


def test_object_order_is_preserved_with_more_objects():
    extra = [_obj(n, 0, b"<< /Type /Test >>") for n in (4, 5, 6)]
    content = _basic_pdf(extra_objects=extra)
    result = PdfStaticAnalyzer().analyze(content)
    assert [o.object_number for o in result.objects] == [1, 2, 3, 4, 5, 6]


def test_metadata_author_creator_producer_title_and_creationdate():
    info_obj = _obj(
        9,
        0,
        b"<< /Author (Jane Doe) /Creator (Aegis) /Producer (Aegis PDF) "
        b"/Title (Report) /Subject (Test) /Keywords (ctf) "
        b"/CreationDate (D:20260101000000) /ModDate (D:20260102000000) >>",
    )
    content = _basic_pdf(extra_objects=[info_obj])
    result = PdfStaticAnalyzer().analyze(content)
    by_key = {item.key: item for item in result.metadata_items}

    assert by_key["Author"].value_preview == "Jane Doe"
    assert by_key["Creator"].value_preview == "Aegis"
    assert by_key["Producer"].value_preview == "Aegis PDF"
    assert by_key["Title"].value_preview == "Report"
    assert by_key["CreationDate"].value_preview == "D:20260101000000"
    assert by_key["ModDate"].value_preview == "D:20260102000000"


def test_hex_string_metadata_value_is_decoded():
    info_obj = _obj(9, 0, b"<< /Title <48656C6C6F> >>")
    content = _basic_pdf(extra_objects=[info_obj])
    result = PdfStaticAnalyzer().analyze(content)
    title = next(item for item in result.metadata_items if item.key == "Title")
    assert title.value_preview == "Hello"


def test_comment_extraction_excludes_header_and_eof():
    content = _basic_pdf(
        footer=(
            b"% a test comment\n"
            b"xref\n0 4\ntrailer\n<< /Root 1 0 R >>\nstartxref\n0\n%%EOF\n"
        )
    )
    result = PdfStaticAnalyzer().analyze(content)
    assert "a test comment" in result.comments
    assert not any(c.startswith("PDF-") for c in result.comments)
    assert "%EOF" not in result.comments


def test_flag_candidates_and_important_metadata_are_detected():
    info_obj = _obj(9, 0, f"<< /Author ({_FLAG}) /Producer (nothing here) >>".encode("latin-1"))
    content = _basic_pdf(extra_objects=[info_obj])
    result = PdfStaticAnalyzer().analyze(content)
    author = next(item for item in result.metadata_items if item.key == "Author")
    assert _FLAG in author.flag_candidates
    assert author.important is True
    producer = next(item for item in result.metadata_items if item.key == "Producer")
    assert producer.important is False
    assert _FLAG in result.flag_candidates


def test_startxref_xref_trailer_root_and_info_are_detected():
    root_info_obj = _obj(9, 0, b"<< /Root 1 0 R /Info 6 0 R >>")
    content = _basic_pdf(extra_objects=[root_info_obj])
    result = PdfStaticAnalyzer().analyze(content)
    assert not any("startxrefが見つかりません" in w for w in result.warnings)
    assert not any("xrefが見つかりません" in w for w in result.warnings)
    assert not any("trailerが見つかりません" in w for w in result.warnings)
    obj9 = next(o for o in result.objects if o.object_number == 9)
    assert "Root" in obj9.keys
    assert "Info" in obj9.keys


# ---------------------------------------------------------------------------
# Stream
# ---------------------------------------------------------------------------


def test_stream_is_detected():
    stream_obj = (
        b"7 0 obj\n<< /Length 4 >>\nstream\nabcd\nendstream\nendobj\n"
    )
    content = _basic_pdf(extra_objects=[stream_obj])
    result = PdfStaticAnalyzer().analyze(content)
    obj7 = next(o for o in result.objects if o.object_number == 7)
    assert obj7.has_stream is True


def test_flatedecode_stream_is_inflated_and_flag_extracted():
    payload = zlib.compress(f"stream body {_FLAG} end".encode())
    stream_obj = (
        f"7 0 obj\n<< /Length {len(payload)} /Filter /FlateDecode >>\nstream\n".encode("latin-1")
        + payload
        + b"\nendstream\nendobj\n"
    )
    content = _basic_pdf(extra_objects=[stream_obj])
    result = PdfStaticAnalyzer().analyze(content)
    obj7 = next(o for o in result.objects if o.object_number == 7)
    assert obj7.has_stream is True
    assert _FLAG in obj7.flag_candidates
    assert _FLAG in result.flag_candidates


def test_asciihexdecode_stream_is_decoded():
    hex_payload = f"stream body {_FLAG} end".encode().hex().encode("ascii")
    stream_obj = (
        b"7 0 obj\n<< /Filter /ASCIIHexDecode >>\nstream\n"
        + hex_payload
        + b">\nendstream\nendobj\n"
    )
    content = _basic_pdf(extra_objects=[stream_obj])
    result = PdfStaticAnalyzer().analyze(content)
    obj7 = next(o for o in result.objects if o.object_number == 7)
    assert _FLAG in obj7.flag_candidates


def test_ascii85decode_stream_is_decoded():
    payload = base64.a85encode(f"stream body {_FLAG} end".encode(), adobe=True)
    stream_obj = (
        b"7 0 obj\n<< /Filter /ASCII85Decode >>\nstream\n"
        + payload
        + b"\nendstream\nendobj\n"
    )
    content = _basic_pdf(extra_objects=[stream_obj])
    result = PdfStaticAnalyzer().analyze(content)
    obj7 = next(o for o in result.objects if o.object_number == 7)
    assert _FLAG in obj7.flag_candidates


def test_stream_decompression_over_limit_is_not_used_for_flags():
    payload = zlib.compress(b"A" * 2_000_000)
    stream_obj = (
        f"7 0 obj\n<< /Length {len(payload)} /Filter /FlateDecode >>\nstream\n".encode("latin-1")
        + payload
        + b"\nendstream\nendobj\n"
    )
    content = _basic_pdf(extra_objects=[stream_obj])
    result = PdfStaticAnalyzer().analyze(content)
    obj7 = next(o for o in result.objects if o.object_number == 7)
    assert obj7.flag_candidates == ()
    assert any("展開に失敗" in w or "サイズ上限" in w for w in result.warnings)


def test_corrupted_flatedecode_stream_is_reported_safely():
    stream_obj = (
        b"7 0 obj\n<< /Filter /FlateDecode >>\nstream\nnot zlib data\nendstream\nendobj\n"
    )
    content = _basic_pdf(extra_objects=[stream_obj])
    result = PdfStaticAnalyzer().analyze(content)
    assert any("FlateDecodeの展開に失敗" in w for w in result.warnings)


def test_stream_endstream_mismatch_is_reported():
    stream_obj = b"7 0 obj\n<< /Filter /FlateDecode >>\nstream\nsome data with no end marker\nendobj\n"
    content = _basic_pdf(extra_objects=[stream_obj])
    result = PdfStaticAnalyzer().analyze(content)
    assert any(
        "stream/endstreamの対応が取れていない" in w for w in result.warnings
    )


# ---------------------------------------------------------------------------
# 危険痕跡
# ---------------------------------------------------------------------------


def test_all_danger_markers_are_detected_as_suspicious_items():
    danger_obj = _obj(
        20,
        0,
        b"<< /S /JavaScript /JS (app.alert(1)) /OpenAction 1 0 R /AA << >> "
        b"/Launch << >> /URI (http://example.com) /EmbeddedFile 21 0 R "
        b"/Filespec (a.txt) /AcroForm << >> /XFA [] /Encrypt 22 0 R >>",
    )
    content = _basic_pdf(extra_objects=[danger_obj])
    result = PdfStaticAnalyzer().analyze(content)
    detected_types = {item.item_type for item in result.suspicious_items}
    assert detected_types == {
        "JavaScript",
        "JS",
        "OpenAction",
        "AA",
        "Launch",
        "URI",
        "EmbeddedFile",
        "Filespec",
        "AcroForm",
        "XFA",
        "Encrypt",
    }
    assert result.encrypted is True


def test_javascript_object_level_suspicious_marker_and_preview():
    js_obj = _obj(20, 0, b"<< /S /JavaScript /JS (app.alert('x')) >>")
    content = _basic_pdf(extra_objects=[js_obj])
    result = PdfStaticAnalyzer().analyze(content)
    obj20 = next(o for o in result.objects if o.object_number == 20)
    assert "/JavaScript" in obj20.suspicious_markers
    assert "/JS" in obj20.suspicious_markers


# ---------------------------------------------------------------------------
# 異常系
# ---------------------------------------------------------------------------


def test_header_mismatch_returns_undetected_result():
    result = PdfStaticAnalyzer().analyze(b"this is not a pdf file at all")
    assert result.valid_header is False
    assert result.objects == ()
    assert result.warnings == ()


def test_missing_eof_is_reported():
    content = _basic_pdf(
        footer=b"xref\n0 4\ntrailer\n<< /Root 1 0 R >>\nstartxref\n0\n"
    )
    result = PdfStaticAnalyzer().analyze(content)
    assert "%%EOFが見つかりません。" in result.warnings


def test_multiple_eof_is_reported():
    content = _basic_pdf(
        footer=(
            b"xref\n0 4\ntrailer\n<< /Root 1 0 R >>\nstartxref\n0\n%%EOF\n"
            b"%%EOF\n"
        )
    )
    result = PdfStaticAnalyzer().analyze(content)
    assert "%%EOFが複数回出現しています。" in result.warnings


def test_missing_startxref_is_reported():
    content = _basic_pdf(
        footer=b"xref\n0 4\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
    )
    result = PdfStaticAnalyzer().analyze(content)
    assert "startxrefが見つかりません。" in result.warnings


def test_missing_xref_is_reported():
    content = _basic_pdf(
        footer=b"trailer\n<< /Root 1 0 R >>\nstartxref\n0\n%%EOF\n"
    )
    result = PdfStaticAnalyzer().analyze(content)
    assert "xrefが見つかりません。" in result.warnings


def test_missing_trailer_is_reported():
    content = _basic_pdf(footer=b"xref\n0 4\nstartxref\n0\n%%EOF\n")
    result = PdfStaticAnalyzer().analyze(content)
    assert "trailerが見つかりません。" in result.warnings


def test_object_endobj_mismatch_is_reported():
    content = _basic_pdf() + b"9 0 obj\n<< /Type /Broken >>\n"
    result = PdfStaticAnalyzer().analyze(content)
    assert "objectとendobjの数が一致しません。" in result.warnings
    assert any("endobjで閉じられていない" in w for w in result.warnings)


def test_object_count_over_limit_is_truncated():
    extra = [_obj(n, 0, b"<< /Type /Filler >>") for n in range(10, 520)]
    content = _basic_pdf(extra_objects=extra)
    result = PdfStaticAnalyzer().analyze(content)
    assert result.truncated is True
    assert any("object数が上限を超えた" in w for w in result.warnings)
    assert len(result.objects) <= 500


def test_truncated_pdf_is_handled_safely():
    content = _basic_pdf()[:-20]
    result = PdfStaticAnalyzer().analyze(content)
    assert result.valid_header is True
    assert isinstance(result.warnings, tuple)


def test_invalid_object_number_zero_is_reported():
    content = _basic_pdf(extra_objects=[_obj(0, 0, b"<< /Type /Weird >>")])
    result = PdfStaticAnalyzer().analyze(content)
    assert any("無効なobject番号です" in w for w in result.warnings)


def test_invalid_generation_number_is_reported():
    content = _basic_pdf(extra_objects=[_obj(9, 70000, b"<< /Type /Weird >>")])
    result = PdfStaticAnalyzer().analyze(content)
    assert any("無効なgeneration番号です" in w for w in result.warnings)


def test_abnormally_large_stream_is_reported():
    huge_body = b"A" * 1_500_000
    stream_obj = b"7 0 obj\n<< >>\nstream\n" + huge_body + b"\nendstream\nendobj\n"
    content = _basic_pdf(extra_objects=[stream_obj])
    result = PdfStaticAnalyzer().analyze(content)
    assert any("異常に大きなstream" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Trailing Data
# ---------------------------------------------------------------------------


def test_trailing_data_after_eof_is_detected():
    base = _basic_pdf()
    content = base + b"PK\x03\x04trailing bytes"
    result = PdfStaticAnalyzer().analyze(content)
    assert result.trailing_data is not None
    assert result.trailing_data.offset == len(base)


def test_trailing_data_detects_zip_magic():
    content = _basic_pdf() + b"PK\x03\x04rest of zip"
    result = PdfStaticAnalyzer().analyze(content)
    assert result.trailing_data.detected_magic == "ZIP"


def test_trailing_data_detects_png_magic():
    content = _basic_pdf() + b"\x89PNG\r\n\x1a\nrest of png"
    result = PdfStaticAnalyzer().analyze(content)
    assert result.trailing_data.detected_magic == "PNG"


def test_trailing_data_extracts_ascii_strings_and_flags():
    content = _basic_pdf() + f"junk {_FLAG} junk".encode()
    result = PdfStaticAnalyzer().analyze(content)
    assert any(_FLAG in s for s in result.trailing_data.strings)
    assert _FLAG in result.trailing_data.flag_candidates
    assert _FLAG in result.flag_candidates


def test_trailing_data_is_bounded_to_analysis_limit():
    content = _basic_pdf() + (b"A" * 2_000_000)
    result = PdfStaticAnalyzer().analyze(content)
    assert result.trailing_data.truncated is True
    assert result.trailing_data.size == 2_000_000


def test_trailing_data_dto_never_holds_full_content():
    content = _basic_pdf() + (b"A" * 2_000_000)
    result = PdfStaticAnalyzer().analyze(content)
    field_names = set(result.trailing_data.__slots__)
    assert "content" not in field_names
    assert "raw" not in field_names
    assert "data" not in field_names
    assert len(result.trailing_data.preview) <= 500


# ---------------------------------------------------------------------------
# 統合
# ---------------------------------------------------------------------------


def test_static_file_analyzer_adds_reserved_prefixed_pdf_strings():
    info_obj = _obj(9, 0, f"<< /Title ({_FLAG}) >>".encode("latin-1"))
    content = _basic_pdf(extra_objects=[info_obj])
    file_input = FileInput("chal.pdf", Path("chal.pdf"), len(content), ".pdf", content)
    result = StaticFileAnalyzer().analyze(file_input)

    assert result.detected_type == "pdf"
    metadata_strings = [s for s in result.strings if s.startswith(PDF_METADATA_PREFIX)]
    assert any("version=1.7" in s for s in metadata_strings)
    info_strings = [s for s in result.strings if s.startswith(PDF_INFO_PREFIX)]
    assert any(_FLAG in s for s in info_strings)


def test_context_builder_shows_dedicated_pdf_analysis_heading_without_duplication():
    content = _basic_pdf() + b"PK\x03\x04trailing"
    file_input = FileInput("chal.pdf", Path("chal.pdf"), len(content), ".pdf", content)
    file_result = StaticFileAnalyzer().analyze(file_input)
    challenge = ChallengeInput(question="PDFを解析してください", files=[file_result])

    context = ChallengeContextBuilder().build(challenge)

    assert "PDF Analysis:" in context
    assert "version=1.7" in context
    assert PDF_METADATA_PREFIX not in context
    assert PDF_TRAILING_PREFIX not in context

    lines = context.splitlines()
    strings_heading_index = lines.index("抽出文字列：")
    following = lines[strings_heading_index + 1 : strings_heading_index + 60]
    plain_string_block = "\n".join(following)
    assert "__AEGIS_PDF_" not in plain_string_block


def test_existing_file_analysis_result_dto_is_unchanged():
    result = FileAnalysisResult("x", 0, ".bin", "unknown", None, [])
    assert result.recursive_encoding_result is None


def test_static_file_analyzer_public_constructor_and_analyze_signature_unchanged():
    analyzer = StaticFileAnalyzer()
    signature = inspect.signature(analyzer.analyze)
    assert list(signature.parameters) == ["file_input"]


def test_pdf_flag_is_solved_via_existing_strings_fast_path_without_ai(tmp_path: Path):
    info_obj = _obj(9, 0, f"<< /Title ({_FLAG}) >>".encode("latin-1"))
    content = _basic_pdf(extra_objects=[info_obj])
    pdf_path = tmp_path / "chal.pdf"
    pdf_path.write_bytes(content)

    controller = MagicMock()
    analyzer = MagicMock()
    analyzer.analyze.return_value = "Forensics"
    service = ChallengeService(controller=controller, analyzer=analyzer)

    result = service.solve("PDFからFlagを見つけてください", [pdf_path])

    assert result.flag == _FLAG
    assert result.confidence == 90
    controller.process_challenge.assert_not_called()


def test_analyzer_source_has_no_forbidden_external_tools_or_execution():
    source = Path("app/file/pdf_static_analyzer.py").read_text(encoding="utf-8")
    for forbidden in (
        "subprocess",
        "os.system",
        "eval(",
        "exec(",
        "PyPDF2",
        "pypdf",
        "pdfminer",
        "mutool",
        "qpdf",
        "pdftotext",
        "exiftool",
        "binwalk",
        "shell=True",
        "tempfile",
        "NamedTemporaryFile",
        "open(",
    ):
        assert forbidden not in source
    assert not re.search(r"(?<!re\.)\bcompile\(", source)


def test_file_size_over_fifty_megabytes_is_not_parsed():
    oversized = b"%PDF-1.7\n" + b"\x00" * 50_000_001
    result = PdfStaticAnalyzer().analyze(oversized)
    assert result.valid_header is True
    assert result.truncated is True
    assert result.objects == ()


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit()])
def test_keyboard_interrupt_and_system_exit_are_not_swallowed(monkeypatch, error):
    analyzer = PdfStaticAnalyzer()
    monkeypatch.setattr(
        analyzer._flag_extractor,
        "extract_all",
        lambda _value: (_ for _ in ()).throw(error),
    )
    with pytest.raises(type(error)):
        analyzer.analyze(_basic_pdf())


def test_zip_png_and_rev_regression_are_unaffected_by_pdf_integration():
    zip_content = b"PK\x05\x06" + b"\x00" * 18
    zip_input = FileInput("empty.zip", Path("empty.zip"), len(zip_content), ".zip", zip_content)
    zip_result = StaticFileAnalyzer().analyze(zip_input)
    assert zip_result.detected_type == "zip"
    assert not any(s.startswith(PDF_METADATA_PREFIX) for s in zip_result.strings)

    png_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    png_input = FileInput("chal.png", Path("chal.png"), len(png_content), ".png", png_content)
    png_result = StaticFileAnalyzer().analyze(png_input)
    assert not any(s.startswith(PDF_METADATA_PREFIX) for s in png_result.strings)

    pe_content = b"MZ" + b"\x00" * 100
    pe_input = FileInput("app.exe", Path("app.exe"), len(pe_content), ".exe", pe_content)
    pe_result = StaticFileAnalyzer().analyze(pe_input)
    assert not any(s.startswith(PDF_METADATA_PREFIX) for s in pe_result.strings)
