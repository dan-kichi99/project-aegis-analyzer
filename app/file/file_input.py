from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class FileInput:
    """読み込んだファイルの基本情報およびバイトデータを保持する DTO。"""

    name: str
    path: Path
    size: int
    extension: str
    content: bytes
