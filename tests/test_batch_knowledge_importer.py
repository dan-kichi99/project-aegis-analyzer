from pathlib import Path

import pytest

from app.analyzer.analyzer import Category
from app.knowledge.batch_knowledge_importer import BatchKnowledgeImporter
from app.knowledge.knowledge_importer import KnowledgeImporter


@pytest.fixture
def batch_importer(tmp_path: Path) -> tuple[BatchKnowledgeImporter, Path]:
    knowledge_dir = tmp_path / "knowledge"
    importer = KnowledgeImporter(base_dir=knowledge_dir)
    batch = BatchKnowledgeImporter(knowledge_importer=importer)
    return batch, knowledge_dir


def test_import_directory_success_multiple_txt(batch_importer: tuple[BatchKnowledgeImporter, Path], tmp_path: Path):
    batch, knowledge_dir = batch_importer
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    # 1. 複数txtファイルを正常に一括importできる
    (source_dir / "rsa.txt").write_text("RSA details", encoding="utf-8")
    (source_dir / "aes.txt").write_text("AES details", encoding="utf-8")

    imported, failed = batch.import_directory(Category.CRYPTO, source_dir)

    # 2. 返却されたimported_filesが保存先Pathになっている
    assert len(failed) == 0
    assert len(imported) == 2
    assert imported[0] == knowledge_dir / "crypto" / "aes.txt"
    assert imported[1] == knowledge_dir / "crypto" / "rsa.txt"
    assert (knowledge_dir / "crypto" / "aes.txt").read_text(encoding="utf-8") == "AES details"


def test_import_directory_sorted_order(batch_importer: tuple[BatchKnowledgeImporter, Path], tmp_path: Path):
    batch, _ = batch_importer
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    # 3. ファイル名順で処理される
    (source_dir / "ssti.txt").write_text("SSTI content", encoding="utf-8")
    (source_dir / "aes.txt").write_text("AES content", encoding="utf-8")
    (source_dir / "rsa.txt").write_text("RSA content", encoding="utf-8")

    imported, _ = batch.import_directory(Category.CRYPTO, source_dir)

    file_names = [p.name for p in imported]
    assert file_names == ["aes.txt", "rsa.txt", "ssti.txt"]


def test_import_directory_ignores_non_txt_files(batch_importer: tuple[BatchKnowledgeImporter, Path], tmp_path: Path):
    batch, knowledge_dir = batch_importer
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    # 4. .txt以外のファイルは無視される
    (source_dir / "valid.txt").write_text("Valid text", encoding="utf-8")
    (source_dir / "readme.md").write_text("Markdown content", encoding="utf-8")
    (source_dir / "image.png").write_bytes(b"fake image")
    (source_dir / "data.json").write_text("{}", encoding="utf-8")

    imported, failed = batch.import_directory(Category.WEB, source_dir)

    assert len(failed) == 0
    assert len(imported) == 1
    assert imported[0] == knowledge_dir / "web" / "valid.txt"


def test_import_directory_ignores_subdirectories(batch_importer: tuple[BatchKnowledgeImporter, Path], tmp_path: Path):
    batch, knowledge_dir = batch_importer
    source_dir = tmp_path / "source"
    sub_dir = source_dir / "sub"
    sub_dir.mkdir(parents=True)

    # 5. サブディレクトリ内のtxtは無視される
    (source_dir / "top.txt").write_text("Top level", encoding="utf-8")
    (sub_dir / "secret.txt").write_text("Sub level secret", encoding="utf-8")

    imported, failed = batch.import_directory(Category.MISC, source_dir)

    assert len(failed) == 0
    assert len(imported) == 1
    assert imported[0] == knowledge_dir / "misc" / "top.txt"


def test_import_directory_empty_dir_returns_empty_tuples(batch_importer: tuple[BatchKnowledgeImporter, Path], tmp_path: Path):
    batch, _ = batch_importer
    source_dir = tmp_path / "empty_source"
    source_dir.mkdir()

    # 6. 空ディレクトリなら ([], [])
    imported, failed = batch.import_directory(Category.CRYPTO, source_dir)
    assert imported == []
    assert failed == []


def test_import_directory_non_existent_source_raises_file_not_found(batch_importer: tuple[BatchKnowledgeImporter, Path], tmp_path: Path):
    batch, _ = batch_importer
    non_existent = tmp_path / "ghost_dir"

    # 7. 存在しないsource_dirなら FileNotFoundError
    with pytest.raises(FileNotFoundError, match="Source directory does not exist"):
        batch.import_directory(Category.CRYPTO, non_existent)


def test_import_directory_source_is_file_raises_value_error(batch_importer: tuple[BatchKnowledgeImporter, Path], tmp_path: Path):
    batch, _ = batch_importer
    file_source = tmp_path / "file.txt"
    file_source.write_text("Not a directory", encoding="utf-8")

    # 8. source_dirがファイルなら ValueError
    with pytest.raises(ValueError, match="Source path is not a directory"):
        batch.import_directory(Category.CRYPTO, file_source)


def test_import_directory_continues_on_individual_failure(batch_importer: tuple[BatchKnowledgeImporter, Path], tmp_path: Path):
    batch, knowledge_dir = batch_importer
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    # 既存ファイルをあらかじめ作成しておく
    crypto_knowledge = knowledge_dir / "crypto"
    crypto_knowledge.mkdir(parents=True)
    (crypto_knowledge / "duplicate.txt").write_text("Existing duplicate", encoding="utf-8")

    (source_dir / "aes.txt").write_text("AES text", encoding="utf-8")
    (source_dir / "duplicate.txt").write_text("Duplicate text", encoding="utf-8")
    (source_dir / "rsa.txt").write_text("RSA text", encoding="utf-8")

    # 9. 1件がFileExistsErrorになっても残りのファイルを処理する
    imported, failed = batch.import_directory(Category.CRYPTO, source_dir)

    assert len(imported) == 2
    assert imported[0] == knowledge_dir / "crypto" / "aes.txt"
    assert imported[1] == knowledge_dir / "crypto" / "rsa.txt"

    assert len(failed) == 1
    failed_src, failed_exc = failed[0]
    assert failed_src == source_dir / "duplicate.txt"
    assert isinstance(failed_exc, FileExistsError)


def test_import_directory_uppercase_extension_handled(batch_importer: tuple[BatchKnowledgeImporter, Path], tmp_path: Path):
    batch, knowledge_dir = batch_importer
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    # 10. .TXTなど大文字拡張子も対象になる
    (source_dir / "upper.TXT").write_text("Upper text", encoding="utf-8")
    (source_dir / "mixed.Txt").write_text("Mixed text", encoding="utf-8")

    imported, failed = batch.import_directory(Category.REV, source_dir)

    assert len(failed) == 0
    assert len(imported) == 2
    assert imported[0] == knowledge_dir / "rev" / "mixed.Txt"
    assert imported[1] == knowledge_dir / "rev" / "upper.TXT"
