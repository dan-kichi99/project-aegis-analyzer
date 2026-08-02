from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class PeSection:
    """PEセクションヘッダーの基本情報。"""

    name: str
    virtual_size: int
    virtual_address: int
    raw_size: int
    raw_offset: int
    characteristics: int
    readable: bool
    writable: bool
    executable: bool
    raw_data_in_bounds: bool


@dataclass(slots=True, frozen=True)
class PeAnalysisResult:
    """PEヘッダーおよびセクションの静的解析結果。"""

    valid_signature: bool
    format: str
    architecture: str
    number_of_sections: int
    timestamp: int
    entry_point_rva: int
    image_base: int
    section_alignment: int
    file_alignment: int
    subsystem: str
    kind: str
    sections: tuple[PeSection, ...]
