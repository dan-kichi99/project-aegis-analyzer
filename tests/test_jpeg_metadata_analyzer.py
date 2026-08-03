import inspect
import struct
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.challenge.challenge_context_builder import ChallengeContextBuilder
from app.challenge.challenge_input import ChallengeInput
from app.challenge.challenge_service import ChallengeService
from app.file.file_analysis_result import FileAnalysisResult
from app.file.file_input import FileInput
from app.file.jpeg_metadata_analyzer import (
    JPEG_INFO_PREFIX,
    JPEG_TRAILING_PREFIX,
    JpegMetadataAnalyzer,
)
from app.file.static_file_analyzer import StaticFileAnalyzer

_FLAG = "picoCTF{jpeg_static_ok}"


def _seg(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def _build_tiff(fields: dict[int, bytes], orientation: int | None = None) -> bytes:
    num_entries = len(fields) + (1 if orientation is not None else 0)
    ifd_offset = 8
    ifd_size = 2 + num_entries * 12 + 4
    data_offset = ifd_offset + ifd_size

    entries = b""
    blob = b""
    running_offset = data_offset
    for tag, value in fields.items():
        value = value + b"\x00"
        entries += struct.pack("<HHI", tag, 2, len(value)) + struct.pack(
            "<I", running_offset
        )
        blob += value
        running_offset += len(value)
    if orientation is not None:
        entries += struct.pack("<HHI", 0x0112, 3, 1) + struct.pack(
            "<H", orientation
        ) + b"\x00\x00"

    ifd = struct.pack("<H", num_entries) + entries + struct.pack("<I", 0)
    return b"II" + struct.pack("<H", 42) + struct.pack("<I", 8) + ifd + blob


def _exif_segment(fields: dict[int, bytes], orientation: int | None = None) -> bytes:
    tiff = _build_tiff(fields, orientation)
    return _seg(0xE1, b"Exif\x00\x00" + tiff)


def _xmp_segment(*, creator=None, title=None, description=None, keywords=None) -> bytes:
    parts = []
    if creator:
        parts.append(f"<dc:creator>{creator}</dc:creator>")
    if description:
        parts.append(f"<dc:description>{description}</dc:description>")
    if title:
        parts.append(f"<dc:title>{title}</dc:title>")
    if keywords:
        parts.append(f"<dc:subject>{keywords}</dc:subject>")
    xml = "<x:xmpmeta><rdf:RDF><rdf:Description>" + "".join(parts) + "</rdf:Description></rdf:RDF></x:xmpmeta>"
    payload = b"http://ns.adobe.com/xap/1.0/\x00" + xml.encode("utf-8")
    return _seg(0xE1, payload)


def _sof0(width: int = 200, height: int = 100, components: int = 3) -> bytes:
    payload = struct.pack(">BHHB", 8, height, width, components)
    for i in range(components):
        payload += bytes([i + 1, 0x11, 0])
    return _seg(0xC0, payload)


def _jfif(major: int = 1, minor: int = 2) -> bytes:
    payload = bytes([ord("J"), ord("F"), ord("I"), ord("F"), 0, major, minor, 0, 1, 0, 1, 0, 0])
    return _seg(0xE0, payload)


def _icc() -> bytes:
    return _seg(0xE2, b"ICC_PROFILE\x00" + b"\x01\x02" + b"\x00" * 20)


def _adobe() -> bytes:
    return _seg(0xEE, b"Adobe" + b"\x00" * 6)


def _com(text: str) -> bytes:
    return _seg(0xFE, text.encode("latin-1"))


def _sos_and_scan() -> bytes:
    return b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00" + b"\x11\x22\x33\x44\x55"


def _jpeg(segments: list[bytes], *, eoi: bool = True) -> bytes:
    content = b"\xff\xd8" + b"".join(segments) + _sos_and_scan()
    if eoi:
        content += b"\xff\xd9"
    return content


# ---------------------------------------------------------------------------
# 正常系
# ---------------------------------------------------------------------------


def test_header_and_soi_are_recognized():
    content = _jpeg([_jfif(), _sof0()])
    result = JpegMetadataAnalyzer().analyze(content)
    assert result.valid_header is True


def test_eoi_and_trailing_boundary_is_correct():
    content = _jpeg([_jfif(), _sof0()])
    result = JpegMetadataAnalyzer().analyze(content)
    assert content[len(content) - 2 :] == b"\xff\xd9"
    assert result.trailing_data is None


def test_app0_jfif_is_detected():
    content = _jpeg([_jfif(1, 2), _sof0()])
    result = JpegMetadataAnalyzer().analyze(content)
    assert result.has_jfif is True
    assert result.jpeg_version == "1.02"
    assert any(s.marker == "APP0" for s in result.segments)


def test_app1_exif_is_detected():
    content = _jpeg([_exif_segment({0x010F: b"Acme"}), _sof0()])
    result = JpegMetadataAnalyzer().analyze(content)
    assert result.has_exif is True
    assert any(s.marker == "APP1" for s in result.segments)


def test_app2_icc_is_detected():
    content = _jpeg([_icc(), _sof0()])
    result = JpegMetadataAnalyzer().analyze(content)
    assert result.has_icc_profile is True
    assert any(s.marker == "APP2" for s in result.segments)


def test_app14_adobe_is_detected():
    content = _jpeg([_adobe(), _sof0()])
    result = JpegMetadataAnalyzer().analyze(content)
    assert result.has_adobe is True
    assert any(s.marker == "APP14" for s in result.segments)


def test_com_segment_is_detected():
    content = _jpeg([_com("a plain comment"), _sof0()])
    result = JpegMetadataAnalyzer().analyze(content)
    assert "a plain comment" in result.comments
    assert any(s.marker == "COM" for s in result.segments)


def test_exif_make_model_software_artist_copyright_datetime_orientation():
    content = _jpeg(
        [
            _exif_segment(
                {
                    0x010F: b"Acme",
                    0x0110: b"Camera3000",
                    0x0131: b"AegisSoft 1.0",
                    0x013B: b"Jane Doe",
                    0x8298: b"(c) Jane",
                    0x0132: b"2026:08:03 12:00:00",
                },
                orientation=6,
            ),
            _sof0(),
        ]
    )
    result = JpegMetadataAnalyzer().analyze(content)
    assert result.make == "Acme"
    assert result.model == "Camera3000"
    assert result.software == "AegisSoft 1.0"
    assert result.artist == "Jane Doe"
    assert result.copyright == "(c) Jane"
    assert result.datetime == "2026:08:03 12:00:00"
    assert result.orientation == 6


def test_xmp_creator_title_description_keywords_are_extracted():
    content = _jpeg(
        [
            _xmp_segment(
                creator="Jane XMP",
                title="My Title",
                description="A description",
                keywords="ctf, flag",
            ),
            _sof0(),
        ]
    )
    result = JpegMetadataAnalyzer().analyze(content)
    assert result.has_xmp is True
    assert result.xmp_creator == "Jane XMP"
    assert result.xmp_title == "My Title"
    assert result.xmp_description == "A description"
    assert result.xmp_keywords == "ctf, flag"


def test_icc_profile_presence_is_recorded_without_full_content():
    content = _jpeg([_icc(), _sof0()])
    result = JpegMetadataAnalyzer().analyze(content)
    icc_segment = next(s for s in result.segments if s.marker == "APP2")
    assert len(icc_segment.preview) <= 500


def test_adobe_app14_presence_is_recorded():
    content = _jpeg([_adobe(), _sof0()])
    result = JpegMetadataAnalyzer().analyze(content)
    assert result.has_adobe is True


def test_jpeg_size_and_color_components_are_extracted():
    content = _jpeg([_sof0(width=640, height=480, components=3)])
    result = JpegMetadataAnalyzer().analyze(content)
    assert result.width == 640
    assert result.height == 480
    assert result.color_components == 3


# ---------------------------------------------------------------------------
# Trailing Data
# ---------------------------------------------------------------------------


def test_trailing_zip_data_is_detected():
    content = _jpeg([_sof0()]) + b"PK\x03\x04trailing zip bytes"
    result = JpegMetadataAnalyzer().analyze(content)
    assert result.trailing_data is not None
    assert result.trailing_data.detected_magic == "ZIP"


def test_trailing_png_data_is_detected():
    content = _jpeg([_sof0()]) + b"\x89PNG\r\n\x1a\ntrailing png bytes"
    result = JpegMetadataAnalyzer().analyze(content)
    assert result.trailing_data.detected_magic == "PNG"


def test_flag_candidate_extraction_from_trailing_and_comment():
    content = (
        _jpeg([_com(f"comment with {_FLAG}"), _sof0()])
        + f"trailing junk {_FLAG}_trail".encode()
    )
    result = JpegMetadataAnalyzer().analyze(content)
    assert _FLAG in result.flag_candidates
    assert any(_FLAG in c for c in result.comments)


def test_comment_flag_candidates_field_contains_flag():
    content = _jpeg([_com(f"secret is {_FLAG}"), _sof0()])
    result = JpegMetadataAnalyzer().analyze(content)
    assert _FLAG in result.flag_candidates


# ---------------------------------------------------------------------------
# 異常系
# ---------------------------------------------------------------------------


def test_corrupt_jpeg_is_handled_safely():
    content = b"\xff\xd8" + b"\xff\xe0\x00\x04" + b"\x00\x00\x00\x00\x00\x00garbage no marker here"
    result = JpegMetadataAnalyzer().analyze(content)
    assert result.valid_header is True
    assert isinstance(result.warnings, tuple)


def test_missing_eoi_is_reported():
    content = _jpeg([_sof0()], eoi=False)
    result = JpegMetadataAnalyzer().analyze(content)
    assert any("EOI" in w for w in result.warnings)
    assert result.trailing_data is None


def test_huge_app_segment_is_reported():
    # JPEGのセグメント長は2バイト(uint16)のため最大65535。上限60,000を超える
    # 現実的に到達可能な最大級のセグメントで異常検出を確認する。
    huge_payload = b"X" * 61_000
    content = (
        b"\xff\xd8"
        + bytes([0xFF, 0xE0])
        + struct.pack(">H", len(huge_payload) + 2)
        + huge_payload
    )
    result = JpegMetadataAnalyzer().analyze(content)
    assert any("異常に大きなAPPセグメント" in w for w in result.warnings)
    assert result.truncated is True


def test_truncated_jpeg_is_handled_safely():
    content = _jpeg([_jfif(), _exif_segment({0x010F: b"Acme"}), _sof0()])[:-10]
    result = JpegMetadataAnalyzer().analyze(content)
    assert result.valid_header is True
    assert isinstance(result.warnings, tuple)


def test_header_mismatch_returns_undetected_result():
    result = JpegMetadataAnalyzer().analyze(b"not a jpeg file")
    assert result.valid_header is False
    assert result.segments == ()
    assert result.warnings == ()


# ---------------------------------------------------------------------------
# 統合
# ---------------------------------------------------------------------------


def test_static_file_analyzer_adds_reserved_prefixed_jpeg_strings():
    content = _jpeg([_jfif(), _sof0(width=320, height=240), _com(_FLAG)])
    file_input = FileInput("chal.jpg", Path("chal.jpg"), len(content), ".jpg", content)
    result = StaticFileAnalyzer().analyze(file_input)

    assert result.detected_type == "jpeg"
    info_strings = [s for s in result.strings if s.startswith(JPEG_INFO_PREFIX)]
    assert any("width=320 height=240" in s for s in info_strings)


def test_context_builder_shows_dedicated_jpeg_analysis_heading_without_duplication():
    content = _jpeg([_jfif(), _sof0()]) + b"PK\x03\x04trailing"
    file_input = FileInput("chal.jpg", Path("chal.jpg"), len(content), ".jpg", content)
    file_result = StaticFileAnalyzer().analyze(file_input)
    challenge = ChallengeInput(question="JPEGを解析してください", files=[file_result])

    context = ChallengeContextBuilder().build(challenge)

    assert "JPEG Analysis:" in context
    assert JPEG_INFO_PREFIX not in context
    assert JPEG_TRAILING_PREFIX not in context


def test_existing_file_analysis_result_dto_is_unchanged():
    result = FileAnalysisResult("x", 0, ".bin", "unknown", None, [])
    assert result.recursive_encoding_result is None


def test_static_file_analyzer_public_constructor_and_analyze_signature_unchanged():
    analyzer = StaticFileAnalyzer()
    signature = inspect.signature(analyzer.analyze)
    assert list(signature.parameters) == ["file_input"]


def test_jpeg_flag_is_solved_via_existing_strings_fast_path_without_ai(tmp_path: Path):
    content = _jpeg([_com(_FLAG), _sof0()])
    jpeg_path = tmp_path / "chal.jpg"
    jpeg_path.write_bytes(content)

    controller = MagicMock()
    analyzer = MagicMock()
    analyzer.analyze.return_value = "Forensics"
    service = ChallengeService(controller=controller, analyzer=analyzer)

    result = service.solve("JPEGからFlagを見つけてください", [jpeg_path])

    assert result.flag == _FLAG
    assert result.confidence == 90
    controller.process_challenge.assert_not_called()


def test_analyzer_source_has_no_forbidden_external_tools_or_execution():
    source = Path("app/file/jpeg_metadata_analyzer.py").read_text(encoding="utf-8")
    for forbidden in (
        "subprocess",
        "os.system",
        "eval(",
        "exec(",
        "Pillow",
        "PIL",
        "cv2",
        "exiftool",
        "ImageMagick",
        "Steghide",
        "OutGuess",
        "JSteg",
        "shell=True",
        "tempfile",
        "NamedTemporaryFile",
        "open(",
    ):
        assert forbidden not in source


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit()])
def test_keyboard_interrupt_and_system_exit_are_not_swallowed(monkeypatch, error):
    analyzer = JpegMetadataAnalyzer()
    monkeypatch.setattr(
        analyzer._flag_extractor,
        "extract_all",
        lambda _value: (_ for _ in ()).throw(error),
    )
    with pytest.raises(type(error)):
        analyzer.analyze(_jpeg([_com("x"), _sof0()]))


def test_full_regression_zip_png_pdf_and_pe_are_unaffected():
    zip_content = b"PK\x05\x06" + b"\x00" * 18
    zip_input = FileInput("empty.zip", Path("empty.zip"), len(zip_content), ".zip", zip_content)
    zip_result = StaticFileAnalyzer().analyze(zip_input)
    assert zip_result.detected_type == "zip"
    assert not any(s.startswith(JPEG_INFO_PREFIX) for s in zip_result.strings)

    png_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    png_input = FileInput("chal.png", Path("chal.png"), len(png_content), ".png", png_content)
    png_result = StaticFileAnalyzer().analyze(png_input)
    assert not any(s.startswith(JPEG_INFO_PREFIX) for s in png_result.strings)

    pdf_content = b"%PDF-1.7\n1 0 obj\n<< >>\nendobj\ntrailer\n<< >>\n%%EOF\n"
    pdf_input = FileInput("chal.pdf", Path("chal.pdf"), len(pdf_content), ".pdf", pdf_content)
    pdf_result = StaticFileAnalyzer().analyze(pdf_input)
    assert not any(s.startswith(JPEG_INFO_PREFIX) for s in pdf_result.strings)

    pe_content = b"MZ" + b"\x00" * 100
    pe_input = FileInput("app.exe", Path("app.exe"), len(pe_content), ".exe", pe_content)
    pe_result = StaticFileAnalyzer().analyze(pe_input)
    assert not any(s.startswith(JPEG_INFO_PREFIX) for s in pe_result.strings)
