from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class WavChunkItem:
    """RIFFチャンク1件分の構造情報（本体は複製しない）。"""

    chunk_id: str
    offset: int
    declared_size: int
    actual_size: int
    known: bool
    detail: str
    truncated: bool


@dataclass(slots=True, frozen=True)
class WavMetadataItem:
    """LIST/INFO・bext・iXML・ID3等から抽出したメタデータ1件分。"""

    source: str
    key: str
    value_preview: str
    offset: int
    important: bool
    flag_candidates: tuple[str, ...]
    truncated: bool


@dataclass(slots=True, frozen=True)
class WavTrailingDataResult:
    """RIFF宣言範囲・最後の有効chunk以降に存在する追加データの安全な要約。"""

    offset: int
    size: int
    preview: str
    detected_magic: str | None
    strings: tuple[str, ...]
    flag_candidates: tuple[str, ...]
    truncated: bool


@dataclass(slots=True, frozen=True)
class WavStaticResult:
    """WAV/RIFFファイル1件分の構造・メタデータ静的解析結果。"""

    valid_header: bool
    riff_declared_size: int | None
    actual_file_size: int
    audio_format: int | None
    format_name: str | None
    channel_count: int | None
    sample_rate: int | None
    byte_rate: int | None
    block_align: int | None
    bits_per_sample: int | None
    duration_seconds: float | None
    chunks: tuple[WavChunkItem, ...]
    metadata_items: tuple[WavMetadataItem, ...]
    warnings: tuple[str, ...]
    flag_candidates: tuple[str, ...]
    trailing_data: WavTrailingDataResult | None
    truncated: bool
