from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class PngChunkItem:
    """PNGチャンク1件分の構造情報（画像データ本体は保持しない）。"""

    chunk_type: str
    offset: int
    length: int
    crc_expected: int | None
    crc_actual: int | None
    crc_valid: bool
    critical: bool
    known: bool
    detail: str


@dataclass(slots=True, frozen=True)
class PngMetadataItem:
    """tEXt/zTXt/iTXtから抽出したテキストメタデータ1件分。"""

    source: str
    key: str
    value_preview: str
    offset: int
    compressed: bool
    important: bool
    flag_candidates: tuple[str, ...]
    truncated: bool


@dataclass(slots=True, frozen=True)
class PngTrailingDataResult:
    """IEND後に存在する追加データの安全な要約。"""

    offset: int
    size: int
    preview: str
    detected_magic: str | None
    strings: tuple[str, ...]
    flag_candidates: tuple[str, ...]
    truncated: bool


@dataclass(slots=True, frozen=True)
class PngMetadataResult:
    """PNGファイル1件分の構造・メタデータ解析結果。"""

    valid_signature: bool
    width: int | None
    height: int | None
    chunks: tuple[PngChunkItem, ...]
    metadata_items: tuple[PngMetadataItem, ...]
    warnings: tuple[str, ...]
    flag_candidates: tuple[str, ...]
    trailing_data: PngTrailingDataResult | None
    truncated: bool
    bit_depth: int | None = None
    color_type: int | None = None
    compression_method: int | None = None
    filter_method: int | None = None
    interlace_method: int | None = None
