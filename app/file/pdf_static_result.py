from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class PdfObjectItem:
    """PDFインダイレクトオブジェクト1件分の構造情報（本文は複製しない）。"""

    object_number: int
    generation_number: int
    offset: int
    has_stream: bool
    keys: tuple[str, ...]
    preview: str
    suspicious_markers: tuple[str, ...]
    flag_candidates: tuple[str, ...]
    truncated: bool


@dataclass(slots=True, frozen=True)
class PdfMetadataItem:
    """/Info辞書等から抽出したメタデータ1件分。"""

    key: str
    value_preview: str
    offset: int
    important: bool
    flag_candidates: tuple[str, ...]
    truncated: bool


@dataclass(slots=True, frozen=True)
class PdfSuspiciousItem:
    """JavaScript・添付ファイル・危険Action等の痕跡1件分。"""

    item_type: str
    object_number: int | None
    offset: int | None
    detail_preview: str
    severity: str


@dataclass(slots=True, frozen=True)
class PdfTrailingDataResult:
    """最後の%%EOF以降に存在する追加データの安全な要約。"""

    offset: int
    size: int
    preview: str
    detected_magic: str | None
    strings: tuple[str, ...]
    flag_candidates: tuple[str, ...]
    truncated: bool


@dataclass(slots=True, frozen=True)
class PdfStaticResult:
    """PDFファイル1件分の構造・メタデータ静的解析結果。"""

    valid_header: bool
    version: str | None
    object_count: int
    objects: tuple[PdfObjectItem, ...]
    metadata_items: tuple[PdfMetadataItem, ...]
    comments: tuple[str, ...]
    suspicious_items: tuple[PdfSuspiciousItem, ...]
    warnings: tuple[str, ...]
    flag_candidates: tuple[str, ...]
    trailing_data: PdfTrailingDataResult | None
    encrypted: bool
    truncated: bool
