import pytest

from app.file.file_loader import FileLoader


def test_load_text_file(tmp_path):
    file_path = tmp_path / "challenge.txt"
    file_path.write_bytes(b"RSA challenge")

    loader = FileLoader()
    result = loader.load(file_path)

    assert result.name == "challenge.txt"
    assert result.extension == ".txt"
    assert result.size == len(b"RSA challenge")
    assert result.content == b"RSA challenge"


def test_load_binary_file(tmp_path):
    file_path = tmp_path / "binary.bin"
    binary_data = b"\x00\x01\xff\xfe"
    file_path.write_bytes(binary_data)

    loader = FileLoader()
    result = loader.load(file_path)

    assert result.name == "binary.bin"
    assert result.extension == ".bin"
    assert result.size == len(binary_data)
    assert result.content == binary_data


def test_load_non_existent_file(tmp_path):
    file_path = tmp_path / "non_existent.txt"

    loader = FileLoader()
    with pytest.raises(FileNotFoundError):
        loader.load(file_path)


def test_load_directory_as_file(tmp_path):
    dir_path = tmp_path / "some_dir"
    dir_path.mkdir()

    loader = FileLoader()
    with pytest.raises(ValueError, match="File path must point to a file."):
        loader.load(dir_path)


def test_load_file_without_extension(tmp_path):
    file_path = tmp_path / "Makefile"
    file_path.write_bytes(b"all: build")

    loader = FileLoader()
    result = loader.load(file_path)

    assert result.name == "Makefile"
    assert result.extension == ""
    assert result.content == b"all: build"


def test_load_empty_file(tmp_path):
    file_path = tmp_path / "empty.dat"
    file_path.write_bytes(b"")

    loader = FileLoader()
    result = loader.load(file_path)

    assert result.name == "empty.dat"
    assert result.extension == ".dat"
    assert result.size == 0
    assert result.content == b""
