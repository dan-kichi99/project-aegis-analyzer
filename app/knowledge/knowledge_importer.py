from pathlib import Path

from app.analyzer.analyzer import Category

_CATEGORY_DIR_MAP: dict[str, str] = {
    Category.CRYPTO: "crypto",
    Category.WEB: "web",
    Category.REV: "rev",
    Category.MISC: "misc",
}


class KnowledgeImporter:
    """ローカルのWriteupや資料をKnowledgeディレクトリへ安全に取り込むクラス。"""

    def __init__(
        self,
        base_dir: Path | str = "data/knowledge",
    ) -> None:
        self._base_dir = Path(base_dir)

    def import_text(
        self,
        category: str,
        filename: str,
        content: str,
    ) -> Path:
        """文字列データを取り込み、指定カテゴリ配下に.txtファイルとして保存する。"""

        if category not in _CATEGORY_DIR_MAP:
            raise ValueError(
                f"Invalid or unsupported category: '{category}'. "
                f"Allowed categories: {list(_CATEGORY_DIR_MAP.keys())}"
            )

        if (
            Path(filename).name != filename
            or ".." in filename
            or "/" in filename
            or "\\" in filename
        ):
            raise ValueError(
                f"Path traversal or invalid filename detected: '{filename}'"
            )

        if not filename.lower().endswith(".txt"):
            raise ValueError(
                f"Only .txt files are allowed. Got: '{filename}'"
            )

        if not content or not content.strip():
            raise ValueError("Content cannot be empty.")

        dir_name = _CATEGORY_DIR_MAP[category]
        target_dir = self._base_dir / dir_name
        target_dir.mkdir(parents=True, exist_ok=True)

        target_file = target_dir / filename

        if target_file.exists():
            raise FileExistsError(
                f"File already exists at target: '{target_file}'"
            )

        target_file.write_text(content, encoding="utf-8")

        return target_file

    def import_file(
        self,
        category: str,
        source_path: Path | str,
    ) -> Path:
        """ローカルに存在する.txtファイルを読み込み、Knowledge配下へ追加する。"""
        src = Path(source_path)

        if not src.exists():
            raise FileNotFoundError(
                f"Source file does not exist: '{src}'"
            )

        if not src.is_file():
            raise ValueError(
                f"Source path is not a file: '{src}'"
            )

        if src.suffix.lower() != ".txt":
            raise ValueError(
                f"Source file must be a .txt file. Got: '{src.name}'"
            )

        content = src.read_text(encoding="utf-8")

        return self.import_text(
            category=category,
            filename=src.name,
            content=content,
        )
