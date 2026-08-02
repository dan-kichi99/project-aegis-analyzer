import io
import struct
import zipfile
import zlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.analyzer.analyzer import Analyzer
from app.challenge.challenge_context_builder import ChallengeContextBuilder
from app.challenge.challenge_input import ChallengeInput
from app.challenge.challenge_service import ChallengeService
from app.file.appended_data_analyzer import (
    MAX_CONTENT_BYTES,
    MAX_PREVIEW_CHARACTERS,
)
from app.file.file_input import FileInput
from app.file.file_loader import FileLoader
from app.file.static_file_analyzer import StaticFileAnalyzer
from tests.test_elf_analyzer import make_elf
from tests.test_pe_analyzer import make_pe


def _input(name: str, content: bytes) -> FileInput:
    path = Path(name)
    return FileInput(
        name=name,
        path=path,
        size=len(content),
        extension=path.suffix,
        content=content,
    )


def _png_chunk(chunk_type: bytes, data: bytes = b"") -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data))
    )


def _png() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IEND")


def _jpeg(scan_data: bytes = b"abc") -> bytes:
    return (
        b"\xff\xd8"
        + b"\xff\xe0\x00\x04AB"
        + b"\xff\xda\x00\x04CD"
        + scan_data
        + b"\xff\xd9"
    )


def _zip(comment: bytes = b"") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("file.txt", b"data")
        archive.comment = comment
    return output.getvalue()


def _analyze(name: str, content: bytes):
    return StaticFileAnalyzer().analyze(_input(name, content))


def test_png_detects_data_after_valid_iend():
    original = _png()
    result = _analyze("image.png", original + b"FLAG{tail}").appended_data

    assert result is not None
    assert result.end_offset == len(original)
    assert result.appended_offset == len(original)
    assert result.content == b"FLAG{tail}"


def test_png_internal_chunk_data_is_not_appended():
    content = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"tEXt", b"Comment\x00internal data")
        + _png_chunk(b"IEND")
    )

    assert _analyze("image.png", content).appended_data is None


@pytest.mark.parametrize(
    "content",
    [
        b"\x89PNG\r\n\x1a\n" + _png_chunk(b"tEXt", b"data"),
        b"\x89PNG\r\n\x1a\n\x00\x00\xff\xffbad",
    ],
)
def test_invalid_or_iendless_png_fails_safely(content):
    assert _analyze("bad.png", content).appended_data is None


def test_jpeg_detects_data_after_eoi():
    original = _jpeg()
    result = _analyze("image.jpg", original + b"trailing").appended_data

    assert result is not None
    assert result.end_offset == len(original)
    assert result.content == b"trailing"


def test_jpeg_stuffed_ff_d9_like_sequence_is_not_early_eoi():
    original = _jpeg(b"abc\xff\x00\xd9def")
    result = _analyze("image.jpg", original + b"tail").appended_data

    assert result is not None
    assert result.end_offset == len(original)


def test_jpeg_without_eoi_fails_safely():
    assert _analyze("bad.jpg", _jpeg()[:-2]).appended_data is None


def test_pdf_uses_last_eof_and_skips_trailing_whitespace():
    content = b"%PDF-1.4\n%%EOF\nupdate\n%%EOF\r\n  FLAG{pdf_tail}"
    result = _analyze("document.pdf", content).appended_data

    assert result is not None
    assert result.content == b"FLAG{pdf_tail}"
    assert result.appended_offset == content.index(b"FLAG{pdf_tail}")


def test_pdf_trailing_whitespace_only_is_not_appended():
    assert _analyze("document.pdf", b"%PDF-1.4\n%%EOF\r\n \t").appended_data is None


def test_zip_detects_data_after_eocd_and_honors_comment():
    original = _zip(b"PK\x05\x06 comment-like bytes")
    result = _analyze("archive.zip", original + b"tail").appended_data

    assert result is not None
    assert result.end_offset == len(original)
    assert result.content == b"tail"


def test_broken_zip_fails_safely():
    result = _analyze("broken.zip", b"PK\x03\x04broken").appended_data

    assert result is None


def test_pe_overlay_uses_existing_section_information():
    original = make_pe() + b"\x00"
    result = _analyze("sample.exe", original + b"overlay").appended_data

    assert result is not None
    assert result.container_type == "pe"
    assert result.end_offset == len(original)
    assert result.content == b"overlay"


def test_elf_tail_uses_existing_section_and_segment_information():
    original = make_elf()
    result = _analyze("sample.elf", original + b"tail").appended_data

    assert result is not None
    assert result.container_type == "elf"
    assert result.end_offset == len(original)
    assert result.content == b"tail"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"PK\x03\x04data", "zip"),
        (b"\x89PNG\r\n\x1a\ndata", "png"),
        (b"%PDF-1.7 data", "pdf"),
        (b"\x7fELFdata", "elf"),
        (b"MZdata", "pe"),
        (b"\x1f\x8bdata", "gzip"),
        (b"7z\xbc\xaf\x27\x1cdata", "7z"),
        (b"Rar!\x1a\x07data", "rar"),
        (b"ordinary", "unknown"),
    ],
)
def test_detects_appended_signature_types(payload, expected):
    result = _analyze("image.png", _png() + payload).appended_data

    assert result is not None
    assert result.detected_type == expected


def test_content_and_preview_are_bounded():
    payload = b"A" * (MAX_CONTENT_BYTES + 100)
    result = _analyze("image.png", _png() + payload).appended_data

    assert result is not None
    assert result.appended_size == len(payload)
    assert result.content is not None
    assert len(result.content) == MAX_CONTENT_BYTES
    assert result.preview is not None
    assert len(result.preview) == MAX_PREVIEW_CHARACTERS


def test_structured_result_is_stored_and_context_is_japanese():
    file_result = _analyze("image.png", _png() + b"PK\x03\x04tail")
    context = ChallengeContextBuilder().build(
        ChallengeInput(question="Analyze", files=[file_result])
    )

    assert file_result.appended_data is not None
    assert "末尾追加データ：" in context
    assert "元形式：PNG" in context
    assert "推定形式：ZIP" in context
    assert "シグネチャ：50 4B 03 04" in context


def test_context_omits_section_without_appended_data():
    file_result = _analyze("image.png", _png())
    context = ChallengeContextBuilder().build(
        ChallengeInput(question="Analyze", files=[file_result])
    )

    assert "末尾追加データ：" not in context


def test_appended_flag_uses_fast_path_without_ai(tmp_path: Path):
    image = tmp_path / "image.png"
    image.write_bytes(_png() + b"FLAG{appended_fast_path}")
    analyzer = MagicMock(spec=Analyzer)
    analyzer.analyze.return_value = "Misc"
    controller = MagicMock()
    service = ChallengeService(
        controller=controller,
        analyzer=analyzer,
        file_loader=FileLoader(),
        file_analyzer=StaticFileAnalyzer(),
    )

    result = service.solve("Analyze", [image])

    assert result.flag == "FLAG{appended_fast_path}"
    assert result.confidence == 90
    assert result.hypothesis is None
    assert result.next_actions == []
    assert result.gemini_prompt is None
    assert f"offset：0x{len(_png()):X}" in result.reason
    assert "推定形式：unknown" in result.reason
    controller.process_challenge.assert_not_called()
    controller.ai_client.generate.assert_not_called()
