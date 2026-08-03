from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class JpegSegmentItem:
    """JPEGセグメント（APPn/COM）1件分の構造情報（本体は複製しない）。"""

    marker: str
    offset: int
    size: int
    preview: str


@dataclass(slots=True, frozen=True)
class JpegTrailingDataResult:
    """EOI(FFD9)以降に存在する追加データの安全な要約。"""

    offset: int
    size: int
    preview: str
    detected_magic: str | None
    strings: tuple[str, ...]
    flag_candidates: tuple[str, ...]
    truncated: bool


@dataclass(slots=True, frozen=True)
class JpegMetadataResult:
    """JPEGファイル1件分の構造・メタデータ静的解析結果。"""

    valid_header: bool
    width: int | None
    height: int | None
    color_components: int | None
    jpeg_version: str | None
    has_jfif: bool
    has_exif: bool
    has_icc_profile: bool
    has_adobe: bool
    has_xmp: bool
    has_gps: bool
    make: str | None
    model: str | None
    software: str | None
    artist: str | None
    copyright: str | None
    datetime: str | None
    orientation: int | None
    xmp_creator: str | None
    xmp_description: str | None
    xmp_title: str | None
    xmp_keywords: str | None
    segments: tuple[JpegSegmentItem, ...]
    comments: tuple[str, ...]
    warnings: tuple[str, ...]
    flag_candidates: tuple[str, ...]
    trailing_data: JpegTrailingDataResult | None
    truncated: bool
