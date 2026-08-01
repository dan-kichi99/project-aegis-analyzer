from pathlib import Path

import pytest

from app.analyzer.analyzer import Category
from app.knowledge.knowledge_importer import KnowledgeImporter


@pytest.fixture
def temp_importer(tmp_path: Path) -> KnowledgeImporter:
    return KnowledgeImporter(base_dir=tmp_path)


def test_import_text_crypto_success(temp_importer: KnowledgeImporter, tmp_path: Path):
    # 1. Cryptoへ正常保存
    content = "RSA Fermat factorization method details."
    result_path = temp_importer.import_text(Category.CRYPTO, "rsa_fermat.txt", content)

    expected_path = tmp_path / "crypto" / "rsa_fermat.txt"
    assert result_path == expected_path
    assert expected_path.exists()

    # 3. 保存ファイルがUTF-8で読める & 4. 内容が元contentと一致
    assert expected_path.read_text(encoding="utf-8") == content


def test_import_text_web_success(temp_importer: KnowledgeImporter, tmp_path: Path):
    # 2. Webへ正常保存
    content = "SQL injection bypass payloads."
    result_path = temp_importer.import_text(Category.WEB, "sqli.txt", content)

    expected_path = tmp_path / "web" / "sqli.txt"
    assert result_path == expected_path
    assert expected_path.exists()
    assert expected_path.read_text(encoding="utf-8") == content


def test_import_text_unknown_category_raises_value_error(temp_importer: KnowledgeImporter):
    # 5. Unknown -> ValueError
    with pytest.raises(ValueError, match="Invalid or unsupported category"):
        temp_importer.import_text(Category.UNKNOWN, "test.txt", "some content")


def test_import_text_invalid_category_raises_value_error(temp_importer: KnowledgeImporter):
    # 6. 不正category -> ValueError
    with pytest.raises(ValueError, match="Invalid or unsupported category"):
        temp_importer.import_text("pwn", "test.txt", "some content")


def test_import_text_non_txt_extension_raises_value_error(temp_importer: KnowledgeImporter):
    # 7. .txt以外 -> ValueError
    with pytest.raises(ValueError, match="Only .txt files are allowed"):
        temp_importer.import_text(Category.CRYPTO, "writeup.md", "content")

    with pytest.raises(ValueError, match="Only .txt files are allowed"):
        temp_importer.import_text(Category.WEB, "doc.pdf", "content")


def test_import_text_empty_content_raises_value_error(temp_importer: KnowledgeImporter):
    # 8. 空content -> ValueError
    with pytest.raises(ValueError, match="Content cannot be empty"):
        temp_importer.import_text(Category.CRYPTO, "empty.txt", "")

    with pytest.raises(ValueError, match="Content cannot be empty"):
        temp_importer.import_text(Category.CRYPTO, "spaces.txt", "   \n\t  ")


def test_import_text_path_traversal_raises_value_error(temp_importer: KnowledgeImporter):
    # 9. ../evil.txt -> ValueError
    with pytest.raises(ValueError, match="Path traversal or invalid filename"):
        temp_importer.import_text(Category.CRYPTO, "../evil.txt", "evil content")

    with pytest.raises(ValueError, match="Path traversal or invalid filename"):
        temp_importer.import_text(Category.CRYPTO, "sub/dir/test.txt", "content")


def test_import_text_duplicate_file_raises_file_exists_error(temp_importer: KnowledgeImporter):
    # 10. 同名ファイル再保存 -> FileExistsError
    temp_importer.import_text(Category.CRYPTO, "same.txt", "initial content")

    with pytest.raises(FileExistsError, match="File already exists"):
        temp_importer.import_text(Category.CRYPTO, "same.txt", "new content")


def test_import_file_success(temp_importer: KnowledgeImporter, tmp_path: Path):
    # 11. import_file()正常動作
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    src_file = source_dir / "notes.txt"
    src_file.write_text("Binary analysis notes", encoding="utf-8")

    result_path = temp_importer.import_file(Category.REV, src_file)

    expected_path = tmp_path / "rev" / "notes.txt"
    assert result_path == expected_path
    assert expected_path.exists()
    assert expected_path.read_text(encoding="utf-8") == "Binary analysis notes"


def test_import_file_not_found_raises_file_not_found_error(temp_importer: KnowledgeImporter, tmp_path: Path):
    # 12. 存在しないsource -> FileNotFoundError
    non_existent = tmp_path / "source" / "ghost.txt"

    with pytest.raises(FileNotFoundError, match="Source file does not exist"):
        temp_importer.import_file(Category.MISC, non_existent)
