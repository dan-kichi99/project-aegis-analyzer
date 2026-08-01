from pathlib import Path

from app.file.file_input import FileInput
from app.file.file_type_detector import FileTypeDetector


def _make_file_input(name: str, content: bytes) -> FileInput:
    path = Path(name)
    return FileInput(
        name=name,
        path=path,
        size=len(content),
        extension=path.suffix,
        content=content,
    )


def test_detect_pe():
    detector = FileTypeDetector()
    file_input = _make_file_input("sample.exe", b"MZ\x90\x00\x03\x00")
    assert detector.detect(file_input) == "pe"


def test_detect_elf():
    detector = FileTypeDetector()
    file_input = _make_file_input("sample.elf", b"\x7fELF\x02\x01\x01")
    assert detector.detect(file_input) == "elf"


def test_detect_png():
    detector = FileTypeDetector()
    file_input = _make_file_input("image.png", b"\x89PNG\r\n\x1a\n\x00\x00")
    assert detector.detect(file_input) == "png"


def test_detect_jpeg():
    detector = FileTypeDetector()
    file_input = _make_file_input("image.jpg", b"\xff\xd8\xff\xe0\x00\x10")
    assert detector.detect(file_input) == "jpeg"


def test_detect_zip():
    detector = FileTypeDetector()
    file_input = _make_file_input("archive.zip", b"PK\x03\x04\x14\x00")
    assert detector.detect(file_input) == "zip"


def test_detect_pdf():
    detector = FileTypeDetector()
    file_input = _make_file_input("doc.pdf", b"%PDF-1.7 header")
    assert detector.detect(file_input) == "pdf"


def test_detect_gif87a():
    detector = FileTypeDetector()
    file_input = _make_file_input("anim.gif", b"GIF87a\x01\x00")
    assert detector.detect(file_input) == "gif"


def test_detect_gif89a():
    detector = FileTypeDetector()
    file_input = _make_file_input("anim.gif", b"GIF89a\x01\x00")
    assert detector.detect(file_input) == "gif"


def test_detect_utf8_text():
    detector = FileTypeDetector()
    file_input = _make_file_input("note.txt", b"RSA challenge text")
    assert detector.detect(file_input) == "text"


def test_detect_utf8_japanese_text():
    detector = FileTypeDetector()
    file_input = _make_file_input("japanese.txt", "RSA暗号の解読問題".encode())
    assert detector.detect(file_input) == "text"


def test_detect_empty():
    detector = FileTypeDetector()
    file_input = _make_file_input("empty.dat", b"")
    assert detector.detect(file_input) == "empty"


def test_detect_unknown_binary():
    detector = FileTypeDetector()
    file_input = _make_file_input("unknown.bin", b"\x00\xff\x00\xfe")
    assert detector.detect(file_input) == "unknown"


def test_detect_fake_extension_png_in_txt():
    detector = FileTypeDetector()
    file_input = _make_file_input("image.txt", b"\x89PNG\r\n\x1a\nfake_content")
    assert detector.detect(file_input) == "png"


def test_detect_elf_without_extension():
    detector = FileTypeDetector()
    file_input = _make_file_input("challenge", b"\x7fELFbinary_data")
    assert detector.detect(file_input) == "elf"
