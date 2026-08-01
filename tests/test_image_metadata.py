import struct
import zlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.analyzer.analyzer import Analyzer
from app.challenge.challenge_service import ChallengeService
from app.file.file_input import FileInput
from app.file.file_loader import FileLoader
from app.file.static_file_analyzer import StaticFileAnalyzer


def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data))
    )


def make_png(chunk_type: bytes, data: bytes) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + png_chunk(chunk_type, data) + png_chunk(
        b"IEND", b""
    )


def make_jpeg_exif(entries: list[tuple[int, bytes, int]]) -> bytes:
    ifd_size = 2 + len(entries) * 12 + 4
    data_offset = 8 + ifd_size
    ifd_entries = []
    extra_data = bytearray()
    for tag, value, value_type in entries:
        count = len(value)
        if len(value) <= 4:
            value_field = value.ljust(4, b"\x00")
        else:
            value_field = struct.pack("<I", data_offset + len(extra_data))
            extra_data.extend(value)
        ifd_entries.append(
            struct.pack("<HHI", tag, value_type, count) + value_field
        )
    tiff = (
        b"II"
        + struct.pack("<H", 42)
        + struct.pack("<I", 8)
        + struct.pack("<H", len(entries))
        + b"".join(ifd_entries)
        + struct.pack("<I", 0)
        + bytes(extra_data)
    )
    exif = b"Exif\x00\x00" + tiff
    return b"\xff\xd8\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif + b"\xff\xd9"


def analyze(name: str, content: bytes):
    path = Path(name)
    return StaticFileAnalyzer().analyze(
        FileInput(
            name=name,
            path=path,
            size=len(content),
            extension=path.suffix,
            content=content,
        )
    )


@pytest.mark.parametrize(
    ("chunk_type", "chunk_data", "expected"),
    [
        (b"tEXt", b"Comment\x00PNG text value", "PNG text value"),
        (
            b"zTXt",
            b"Comment\x00\x00" + zlib.compress(b"compressed text"),
            "compressed text",
        ),
        (
            b"iTXt",
            b"Comment\x00\x00\x00\x00\x00international text",
            "international text",
        ),
    ],
)
def test_extracts_png_text_chunks(chunk_type, chunk_data, expected):
    result = analyze("metadata.png", make_png(chunk_type, chunk_data))

    assert expected in result.strings


def test_extracts_jpeg_image_description():
    jpeg = make_jpeg_exif([(0x010E, b"EXIF description\x00", 2)])

    assert "EXIF description" in analyze("photo.jpg", jpeg).strings


def test_extracts_jpeg_xp_comment():
    comment = "JPEG comment\x00".encode("utf-16-le")
    jpeg = make_jpeg_exif([(0x9C9C, comment, 1)])

    assert "JPEG comment" in analyze("photo.jpg", jpeg).strings


def test_png_metadata_flag_uses_fast_path_without_ai(tmp_path: Path):
    image_path = tmp_path / "flag.png"
    image_path.write_bytes(make_png(b"tEXt", b"Comment\x00FLAG{png_metadata}"))
    analyzer = MagicMock(spec=Analyzer)
    analyzer.analyze.return_value = "Misc"
    controller = MagicMock()
    service = ChallengeService(
        controller=controller,
        analyzer=analyzer,
        file_loader=FileLoader(),
        file_analyzer=StaticFileAnalyzer(),
    )

    result = service.solve("Analyze image", [image_path])

    assert result.flag == "FLAG{png_metadata}"
    controller.process_challenge.assert_not_called()
    controller.ai_client.generate.assert_not_called()


def test_metadata_base64_is_decoded():
    png = make_png(b"tEXt", b"Comment\x00RkxBR3ttZXRhX2I2NH0=")

    assert "FLAG{meta_b64}" in analyze("base64.png", png).strings


def test_metadata_hex_is_decoded():
    png = make_png(b"tEXt", b"Comment\x00464c41477b6d6574615f6865787d")

    assert "FLAG{meta_hex}" in analyze("hex.png", png).strings


def test_duplicate_metadata_string_is_not_added():
    png = make_png(b"tEXt", b"Comment\x00duplicate metadata")
    result = analyze("duplicate.png", png)

    assert result.strings.count("duplicate metadata") == 1


def test_metadata_keeps_existing_strings_limit():
    chunks = b"".join(
        png_chunk(b"tEXt", f"Key{index}\x00value-{index}".encode())
        for index in range(250)
    )
    png = b"\x89PNG\r\n\x1a\n" + chunks + png_chunk(b"IEND", b"")

    assert len(analyze("limit.png", png).strings) <= 200


def test_normal_png_analysis_is_preserved():
    result = analyze("plain.png", make_png(b"IEND", b""))

    assert result.detected_type == "png"
    assert result.text_content is None


def test_normal_jpeg_analysis_is_preserved():
    result = analyze("plain.jpg", b"\xff\xd8\xff\xd9")

    assert result.detected_type == "jpeg"
    assert result.text_content is None


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("broken.png", b"\x89PNG\r\n\x1a\nbroken"),
        ("broken.jpg", b"\xff\xd8\xff\xe1\x00\x20broken"),
    ],
)
def test_broken_image_does_not_raise(name, content):
    result = analyze(name, content)

    assert result.detected_type in {"png", "jpeg"}
