from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class ElfSegment:
    segment_type: str
    file_offset: int
    virtual_address: int
    file_size: int
    memory_size: int
    flags: int
    alignment: int
    readable: bool
    writable: bool
    executable: bool
    data_in_bounds: bool


@dataclass(slots=True, frozen=True)
class ElfSection:
    name: str
    section_type: str
    flags: int
    virtual_address: int
    file_offset: int
    size: int
    executable: bool
    writable: bool
    allocatable: bool
    data_in_bounds: bool


@dataclass(slots=True, frozen=True)
class ElfAnalysisResult:
    valid_signature: bool
    elf_class: str
    endianness: str
    architecture: str
    file_type: str
    entry_point: int
    program_header_offset: int
    section_header_offset: int
    program_header_count: int
    section_header_count: int
    flags: int
    interpreter: str | None
    sections: tuple[ElfSection, ...]
    segments: tuple[ElfSegment, ...]
