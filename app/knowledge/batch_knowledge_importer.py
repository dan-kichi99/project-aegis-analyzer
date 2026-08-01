from pathlib import Path

from app.knowledge.knowledge_importer import KnowledgeImporter


class BatchKnowledgeImporter:
    """ディレクトリ内の複数ナレッジファイルを一括取り込みするクラス。"""

    def __init__(
        self,
        knowledge_importer: KnowledgeImporter,
    ) -> None:
        self._knowledge_importer = knowledge_importer

    def import_directory(
        self,
        category: str,
        source_dir: Path | str,
    ) -> tuple[list[Path], list[tuple[Path, Exception]]]:
        """指定ディレクトリ直下の.txtファイルを一括でKnowledgeへ取り込む。"""
        src_dir = Path(source_dir)

        if not src_dir.exists():
            raise FileNotFoundError(
                f"Source directory does not exist: '{src_dir}'"
            )

        if not src_dir.is_dir():
            raise ValueError(
                f"Source path is not a directory: '{src_dir}'"
            )

        target_files = [
            file_path
            for file_path in src_dir.iterdir()
            if file_path.is_file()
            and file_path.suffix.lower() == ".txt"
        ]

        if not target_files:
            return ([], [])

        target_files.sort(key=lambda file_path: file_path.name)

        imported_files: list[Path] = []
        failed_files: list[tuple[Path, Exception]] = []

        for file_path in target_files:
            try:
                saved_path = self._knowledge_importer.import_file(
                    category=category,
                    source_path=file_path,
                )
                imported_files.append(saved_path)
            except Exception as exc:
                failed_files.append((file_path, exc))

        return (imported_files, failed_files)
