import inspect
import struct
import zlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.challenge.challenge_context_builder import ChallengeContextBuilder
from app.challenge.challenge_input import ChallengeInput
from app.challenge.challenge_service import ChallengeService
from app.file.file_analysis_result import FileAnalysisResult
from app.file.file_input import FileInput
from app.file.png_metadata_analyzer import (
    PNG_FLAG_PREFIX,
    PNG_METADATA_PREFIX,
    PNG_TRAILING_PREFIX,
    PngMetadataAnalyzer,
)
from app.file.static_file_analyzer import StaticFileAnalyzer

_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_FLAG = "picoCTF{png_metadata_ok}"


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def _corrupt_crc(chunk_bytes: bytes) -> bytes:
    corrupted = bytearray(chunk_bytes)
    corrupted[-1] ^= 0xFF
    return bytes(corrupted)


def _ihdr_data(
    width: int = 800,
    height: int = 600,
    bit_depth: int = 8,
    color_type: int = 2,
    compression: int = 0,
    filter_method: int = 0,
    interlace: int = 0,
) -> bytes:
    return struct.pack(
        ">IIBBBBB",
        width,
        height,
        bit_depth,
        color_type,
        compression,
        filter_method,
        interlace,
    )


def _text_chunk(keyword: str, value: str) -> bytes:
    return _chunk(b"tEXt", f"{keyword}\x00{value}".encode("latin-1"))


def _ztxt_chunk(keyword: str, value: str) -> bytes:
    payload = keyword.encode("latin-1") + b"\x00\x00" + zlib.compress(
        value.encode("latin-1")
    )
    return _chunk(b"zTXt", payload)


def _itxt_chunk(
    keyword: str, value: str, *, compressed: bool = False, translated: str = ""
) -> bytes:
    text_bytes = value.encode("utf-8")
    compression_flag = 1 if compressed else 0
    if compressed:
        text_bytes = zlib.compress(text_bytes)
    payload = (
        keyword.encode("latin-1")
        + b"\x00"
        + bytes([compression_flag, 0])
        + b"\x00"
        + translated.encode("utf-8")
        + b"\x00"
        + text_bytes
    )
    return _chunk(b"iTXt", payload)


def _png(chunks: list[bytes]) -> bytes:
    return _SIGNATURE + b"".join(chunks)


def _full_valid_png(*, extra_chunks: list[bytes] | None = None) -> bytes:
    chunks = [
        _chunk(b"IHDR", _ihdr_data()),
        _text_chunk("Comment", _FLAG),
        _ztxt_chunk("Author", "zlib compressed text value"),
        _itxt_chunk("Description", "uncompressed itxt value"),
        _itxt_chunk("Title", "compressed itxt value", compressed=True),
        _chunk(b"pHYs", struct.pack(">IIB", 2835, 2835, 1)),
        _chunk(b"tIME", struct.pack(">HBBBBB", 2026, 8, 3, 12, 30, 0)),
        _chunk(b"gAMA", struct.pack(">I", 45455)),
        _chunk(b"sRGB", bytes([0])),
        _chunk(b"eXIf", b"II*\x00" + b"\x00" * 10),
    ]
    if extra_chunks:
        chunks.extend(extra_chunks)
    chunks.append(_chunk(b"IDAT", b"\x00" * 10))
    chunks.append(_chunk(b"IEND", b""))
    return _png(chunks)


# ---------------------------------------------------------------------------
# 正常系
# ---------------------------------------------------------------------------


def test_signature_ihdr_dimensions_and_bit_depth_are_parsed():
    result = PngMetadataAnalyzer().analyze(_full_valid_png())
    assert result.valid_signature is True
    assert result.width == 800
    assert result.height == 600
    assert result.bit_depth == 8
    assert result.color_type == 2
    assert result.compression_method == 0
    assert result.filter_method == 0
    assert result.interlace_method == 0
    ihdr = next(c for c in result.chunks if c.chunk_type == "IHDR")
    assert "width=800" in ihdr.detail and "bit_depth=8" in ihdr.detail


def test_text_ztxt_itxt_uncompressed_and_compressed_extract_metadata():
    result = PngMetadataAnalyzer().analyze(_full_valid_png())
    by_key = {item.key: item for item in result.metadata_items}

    assert by_key["Comment"].source == "tEXt"
    assert by_key["Comment"].value_preview == _FLAG
    assert by_key["Comment"].compressed is False

    assert by_key["Author"].source == "zTXt"
    assert by_key["Author"].value_preview == "zlib compressed text value"
    assert by_key["Author"].compressed is True

    assert by_key["Description"].source == "iTXt"
    assert by_key["Description"].value_preview == "uncompressed itxt value"
    assert by_key["Description"].compressed is False

    assert by_key["Title"].source == "iTXt"
    assert by_key["Title"].value_preview == "compressed itxt value"
    assert by_key["Title"].compressed is True


def test_phys_time_gama_srgb_exif_chunks_are_parsed():
    result = PngMetadataAnalyzer().analyze(_full_valid_png())
    details = {c.chunk_type: c for c in result.chunks}

    assert "pixels_per_unit_x=2835" in details["pHYs"].detail
    assert "unit_specifier=1" in details["pHYs"].detail

    assert "2026-08-03 12:30:00" == details["tIME"].detail

    assert "gamma=45455" in details["gAMA"].detail
    assert "0.45455" in details["gAMA"].detail

    assert details["sRGB"].detail == "rendering_intent=0"

    assert "payload_size=14" in details["eXIf"].detail
    assert "byte_order=II" in details["eXIf"].detail


def test_crc_is_valid_for_all_chunks_in_well_formed_png():
    result = PngMetadataAnalyzer().analyze(_full_valid_png())
    assert result.chunks
    assert all(chunk.crc_valid for chunk in result.chunks)
    assert not result.warnings


def test_flag_candidates_and_important_keywords_are_detected():
    result = PngMetadataAnalyzer().analyze(_full_valid_png())
    assert _FLAG in result.flag_candidates
    by_key = {item.key: item for item in result.metadata_items}
    assert by_key["Comment"].important is True
    assert _FLAG in by_key["Comment"].flag_candidates
    assert by_key["Author"].important is True
    assert by_key["Description"].important is True


def test_chunk_order_is_preserved():
    result = PngMetadataAnalyzer().analyze(_full_valid_png())
    assert [c.chunk_type for c in result.chunks] == [
        "IHDR",
        "tEXt",
        "zTXt",
        "iTXt",
        "iTXt",
        "pHYs",
        "tIME",
        "gAMA",
        "sRGB",
        "eXIf",
        "IDAT",
        "IEND",
    ]


# ---------------------------------------------------------------------------
# 異常系
# ---------------------------------------------------------------------------


def test_signature_mismatch_returns_undetected_result():
    result = PngMetadataAnalyzer().analyze(b"not a png file")
    assert result.valid_signature is False
    assert result.chunks == ()
    assert result.warnings == ()
    assert result.width is None


def test_missing_ihdr_is_reported():
    chunks = [_chunk(b"IEND", b"")]
    result = PngMetadataAnalyzer().analyze(_png(chunks))
    assert "IHDRが見つかりません。" in result.warnings
    assert result.width is None


def test_ihdr_not_first_chunk_is_reported():
    chunks = [
        _text_chunk("Comment", "before ihdr"),
        _chunk(b"IHDR", _ihdr_data()),
        _chunk(b"IEND", b""),
    ]
    result = PngMetadataAnalyzer().analyze(_png(chunks))
    assert "IHDRが先頭chunkではありません。" in result.warnings


def test_duplicate_ihdr_is_reported():
    chunks = [
        _chunk(b"IHDR", _ihdr_data()),
        _chunk(b"IHDR", _ihdr_data()),
        _chunk(b"IEND", b""),
    ]
    result = PngMetadataAnalyzer().analyze(_png(chunks))
    assert "IHDRが複数回出現しています。" in result.warnings


def test_missing_iend_is_reported():
    chunks = [_chunk(b"IHDR", _ihdr_data())]
    result = PngMetadataAnalyzer().analyze(_png(chunks))
    assert "IENDが見つかりません。" in result.warnings


def test_duplicate_iend_is_reported():
    chunks = [
        _chunk(b"IHDR", _ihdr_data()),
        _chunk(b"IEND", b""),
        _chunk(b"IEND", b""),
    ]
    result = PngMetadataAnalyzer().analyze(_png(chunks))
    assert "IENDが複数回出現しています。" in result.warnings
    assert len([c for c in result.chunks if c.chunk_type == "IEND"]) == 2


def test_crc_mismatch_is_reported_without_stopping_analysis():
    chunks = [
        _chunk(b"IHDR", _ihdr_data()),
        _corrupt_crc(_text_chunk("Comment", _FLAG)),
        _chunk(b"IEND", b""),
    ]
    result = PngMetadataAnalyzer().analyze(_png(chunks))
    text_chunk = next(c for c in result.chunks if c.chunk_type == "tEXt")
    assert text_chunk.crc_valid is False
    assert any("CRC不一致" in w for w in result.warnings)
    assert next(c for c in result.chunks if c.chunk_type == "IEND")


def test_truncated_chunk_header_is_reported_safely():
    content = _png([_chunk(b"IHDR", _ihdr_data()), _chunk(b"IEND", b"")])
    truncated_content = content[:-3]
    result = PngMetadataAnalyzer().analyze(truncated_content)
    assert result.valid_signature is True
    assert result.truncated is True
    assert any("切り詰められて" in w or "範囲外" in w for w in result.warnings)


def test_chunk_beyond_file_bounds_is_reported():
    good = _chunk(b"IHDR", _ihdr_data())
    bad_length_chunk = struct.pack(">I", 1000) + b"tEXt" + b"short"
    content = _SIGNATURE + good + bad_length_chunk
    result = PngMetadataAnalyzer().analyze(content)
    assert result.truncated is True
    assert any("範囲外" in w for w in result.warnings)


def test_abnormally_large_chunk_length_is_reported():
    good = _chunk(b"IHDR", _ihdr_data())
    huge_header = struct.pack(">I", 0xFFFFFFF0) + b"AbCd"
    content = _SIGNATURE + good + huge_header
    result = PngMetadataAnalyzer().analyze(content)
    assert result.truncated is True
    assert any("異常に大きい" in w for w in result.warnings)


def test_unknown_critical_chunk_is_reported():
    chunks = [
        _chunk(b"IHDR", _ihdr_data()),
        _chunk(b"TEST", b"payload"),
        _chunk(b"IEND", b""),
    ]
    result = PngMetadataAnalyzer().analyze(_png(chunks))
    unknown_chunk = next(c for c in result.chunks if c.chunk_type == "TEST")
    assert unknown_chunk.critical is True
    assert unknown_chunk.known is False
    assert any("未知のcritical chunk" in w for w in result.warnings)


def test_width_zero_is_reported():
    chunks = [_chunk(b"IHDR", _ihdr_data(width=0)), _chunk(b"IEND", b"")]
    result = PngMetadataAnalyzer().analyze(_png(chunks))
    assert "widthが0です。" in result.warnings


def test_height_zero_is_reported():
    chunks = [_chunk(b"IHDR", _ihdr_data(height=0)), _chunk(b"IEND", b"")]
    result = PngMetadataAnalyzer().analyze(_png(chunks))
    assert "heightが0です。" in result.warnings


def test_invalid_bit_depth_color_type_combination_is_reported():
    chunks = [
        _chunk(b"IHDR", _ihdr_data(bit_depth=3, color_type=2)),
        _chunk(b"IEND", b""),
    ]
    result = PngMetadataAnalyzer().analyze(_png(chunks))
    assert any("組み合わせが不正" in w for w in result.warnings)


def test_invalid_compression_method_is_reported():
    chunks = [
        _chunk(b"IHDR", _ihdr_data(compression=5)),
        _chunk(b"IEND", b""),
    ]
    result = PngMetadataAnalyzer().analyze(_png(chunks))
    assert "compression methodが0ではありません。" in result.warnings


def test_invalid_filter_method_is_reported():
    chunks = [
        _chunk(b"IHDR", _ihdr_data(filter_method=5)),
        _chunk(b"IEND", b""),
    ]
    result = PngMetadataAnalyzer().analyze(_png(chunks))
    assert "filter methodが0ではありません。" in result.warnings


def test_invalid_interlace_method_is_reported():
    chunks = [
        _chunk(b"IHDR", _ihdr_data(interlace=9)),
        _chunk(b"IEND", b""),
    ]
    result = PngMetadataAnalyzer().analyze(_png(chunks))
    assert "interlace methodが0または1ではありません。" in result.warnings


def test_corrupted_zlib_stream_in_ztxt_is_ignored_safely():
    payload = b"Author\x00\x00" + b"not a valid zlib stream"
    chunks = [
        _chunk(b"IHDR", _ihdr_data()),
        _chunk(b"zTXt", payload),
        _chunk(b"IEND", b""),
    ]
    result = PngMetadataAnalyzer().analyze(_png(chunks))
    assert not any(item.source == "zTXt" for item in result.metadata_items)
    assert any("展開に失敗" in w for w in result.warnings)


def test_ztxt_decompression_over_limit_is_ignored_safely():
    compressed = zlib.compress(b"A" * 2_000_000)
    payload = b"Author\x00\x00" + compressed
    chunks = [
        _chunk(b"IHDR", _ihdr_data()),
        _chunk(b"zTXt", payload),
        _chunk(b"IEND", b""),
    ]
    result = PngMetadataAnalyzer().analyze(_png(chunks))
    assert not any(item.source == "zTXt" for item in result.metadata_items)
    assert any("展開に失敗" in w or "サイズ上限" in w for w in result.warnings)


def test_invalid_utf8_itxt_text_is_ignored_safely():
    payload = (
        b"Description\x00" + bytes([0, 0]) + b"\x00" + b"\x00" + b"\xff\xfe\xfd"
    )
    chunks = [
        _chunk(b"IHDR", _ihdr_data()),
        _chunk(b"iTXt", payload),
        _chunk(b"IEND", b""),
    ]
    result = PngMetadataAnalyzer().analyze(_png(chunks))
    assert not any(item.source == "iTXt" for item in result.metadata_items)
    assert any("UTF-8として不正" in w for w in result.warnings)


def test_chunk_count_over_limit_is_truncated():
    filler = [_chunk(b"sRGB", bytes([0])) for _ in range(520)]
    chunks = [_chunk(b"IHDR", _ihdr_data()), *filler, _chunk(b"IEND", b"")]
    result = PngMetadataAnalyzer().analyze(_png(chunks))
    assert result.truncated is True
    assert any("chunk数が上限を超えた" in w for w in result.warnings)
    assert len(result.chunks) <= 500


# ---------------------------------------------------------------------------
# Trailing Data
# ---------------------------------------------------------------------------


def test_trailing_data_after_iend_is_detected():
    content = _full_valid_png() + b"PK\x03\x04" + b"trailing bytes here"
    result = PngMetadataAnalyzer().analyze(content)
    assert result.trailing_data is not None
    assert result.trailing_data.offset == len(_full_valid_png())
    assert result.trailing_data.size == len(b"PK\x03\x04trailing bytes here")


def test_trailing_data_detects_zip_magic():
    content = _full_valid_png() + b"PK\x03\x04rest of zip data"
    result = PngMetadataAnalyzer().analyze(content)
    assert result.trailing_data.detected_magic == "ZIP"


def test_trailing_data_detects_pdf_magic():
    content = _full_valid_png() + b"%PDF-1.4\nrest of pdf data"
    result = PngMetadataAnalyzer().analyze(content)
    assert result.trailing_data.detected_magic == "PDF"


def test_trailing_data_extracts_ascii_strings():
    content = _full_valid_png() + b"\x00\x00hidden_marker_string\x00\x00"
    result = PngMetadataAnalyzer().analyze(content)
    assert "hidden_marker_string" in result.trailing_data.strings


def test_trailing_data_extracts_flag_candidates():
    trailing_flag = "picoCTF{trailing_data_flag}"
    content = _full_valid_png() + f"junk {trailing_flag} junk".encode()
    result = PngMetadataAnalyzer().analyze(content)
    assert trailing_flag in result.trailing_data.flag_candidates
    assert trailing_flag in result.flag_candidates


def test_trailing_data_is_bounded_to_analysis_limit():
    content = _full_valid_png() + (b"A" * 2_000_000)
    result = PngMetadataAnalyzer().analyze(content)
    assert result.trailing_data.truncated is True
    assert result.trailing_data.size == 2_000_000


def test_trailing_data_dto_never_holds_full_content():
    field_names = set(PngMetadataAnalyzer().analyze(
        _full_valid_png() + (b"A" * 2_000_000)
    ).trailing_data.__slots__)
    assert "content" not in field_names
    assert "raw" not in field_names
    assert "data" not in field_names
    result = PngMetadataAnalyzer().analyze(_full_valid_png() + (b"A" * 2_000_000))
    assert len(result.trailing_data.preview) <= 500


# ---------------------------------------------------------------------------
# 統合
# ---------------------------------------------------------------------------


def test_static_file_analyzer_adds_reserved_prefixed_png_strings():
    content = _full_valid_png()
    file_input = FileInput("chal.png", Path("chal.png"), len(content), ".png", content)
    result = StaticFileAnalyzer().analyze(file_input)

    assert result.detected_type == "png"
    metadata_strings = [
        s for s in result.strings if s.startswith(PNG_METADATA_PREFIX)
    ]
    assert any("width=800 height=600" in s for s in metadata_strings)
    flag_strings = [s for s in result.strings if s.startswith(PNG_FLAG_PREFIX)]
    assert any(_FLAG in s for s in flag_strings)


def test_context_builder_shows_dedicated_png_metadata_heading_without_duplication():
    content = _full_valid_png() + b"PK\x03\x04trailing"
    file_input = FileInput("chal.png", Path("chal.png"), len(content), ".png", content)
    file_result = StaticFileAnalyzer().analyze(file_input)
    challenge = ChallengeInput(question="PNGを解析してください", files=[file_result])

    context = ChallengeContextBuilder().build(challenge)

    assert "PNG Metadata:" in context
    assert "width=800 height=600" in context
    assert PNG_METADATA_PREFIX not in context
    assert PNG_TRAILING_PREFIX not in context

    lines = context.splitlines()
    strings_heading_index = lines.index("抽出文字列：")
    following = lines[strings_heading_index + 1 : strings_heading_index + 60]
    plain_string_block = "\n".join(following)
    assert "__AEGIS_PNG_" not in plain_string_block


def test_existing_file_analysis_result_dto_is_unchanged():
    result = FileAnalysisResult("x", 0, ".bin", "unknown", None, [])
    assert result.recursive_encoding_result is None


def test_static_file_analyzer_public_constructor_and_analyze_signature_unchanged():
    analyzer = StaticFileAnalyzer()
    signature = inspect.signature(analyzer.analyze)
    assert list(signature.parameters) == ["file_input"]


def test_png_flag_is_solved_via_existing_strings_fast_path_without_ai(
    tmp_path: Path,
):
    content = _full_valid_png()
    png_path = tmp_path / "chal.png"
    png_path.write_bytes(content)

    controller = MagicMock()
    analyzer = MagicMock()
    analyzer.analyze.return_value = "Forensics"
    service = ChallengeService(controller=controller, analyzer=analyzer)

    result = service.solve("PNGからFlagを見つけてください", [png_path])

    assert result.flag == _FLAG
    assert result.confidence == 90
    controller.process_challenge.assert_not_called()


def test_analyzer_source_has_no_forbidden_external_tools_or_execution():
    source = Path("app/file/png_metadata_analyzer.py").read_text(encoding="utf-8")
    for forbidden in (
        "subprocess",
        "os.system",
        "eval(",
        "exec(",
        "compile(",
        "Pillow",
        "PIL",
        "cv2",
        "exiftool",
        "pngcheck",
        "binwalk",
        "shell=True",
        "tempfile",
        "NamedTemporaryFile",
        "open(",
    ):
        assert forbidden not in source


def test_empty_input_is_handled_safely():
    result = PngMetadataAnalyzer().analyze(b"")
    assert result.valid_signature is False


def test_file_size_over_fifty_megabytes_is_not_parsed():
    oversized = _SIGNATURE + b"\x00" * 50_000_001
    result = PngMetadataAnalyzer().analyze(oversized)
    assert result.valid_signature is True
    assert result.truncated is True
    assert result.chunks == ()


def test_metadata_item_count_over_limit_is_truncated():
    text_chunks = [
        _text_chunk(f"Key{i}", f"value-{i}") for i in range(210)
    ]
    chunks = [_chunk(b"IHDR", _ihdr_data()), *text_chunks, _chunk(b"IEND", b"")]
    result = PngMetadataAnalyzer().analyze(_png(chunks))
    assert len(result.metadata_items) <= 200
    assert result.truncated is True


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit()])
def test_keyboard_interrupt_and_system_exit_are_not_swallowed(monkeypatch, error):
    analyzer = PngMetadataAnalyzer()
    monkeypatch.setattr(
        analyzer._flag_extractor,
        "extract_all",
        lambda _value: (_ for _ in ()).throw(error),
    )
    with pytest.raises(type(error)):
        analyzer.analyze(_full_valid_png())


def test_zip_and_pe_elf_regression_are_unaffected_by_png_integration():
    zip_content = b"PK\x05\x06" + b"\x00" * 18
    zip_input = FileInput("empty.zip", Path("empty.zip"), len(zip_content), ".zip", zip_content)
    zip_result = StaticFileAnalyzer().analyze(zip_input)
    assert zip_result.detected_type == "zip"
    assert not any(s.startswith(PNG_METADATA_PREFIX) for s in zip_result.strings)

    pe_content = b"MZ" + b"\x00" * 100
    pe_input = FileInput("app.exe", Path("app.exe"), len(pe_content), ".exe", pe_content)
    pe_result = StaticFileAnalyzer().analyze(pe_input)
    assert not any(s.startswith(PNG_METADATA_PREFIX) for s in pe_result.strings)
