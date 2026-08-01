from pathlib import Path

from app.file.file_input import FileInput


class FileLoader:
    """ローカルファイルを安全に検証・読込して FileInput DTO を生成するローダー。"""

    def load(self, file_path: str | Path) -> FileInput:
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        if not path.is_file():
            raise ValueError("File path must point to a file.")

        content = path.read_bytes()
        size = len(content)
        name = path.name
        extension = path.suffix

        return FileInput(
            name=name,
            path=path,
            size=size,
            extension=extension,
            content=content,
        )
