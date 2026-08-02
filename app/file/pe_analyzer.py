import struct

from app.file.file_input import FileInput
from app.file.pe_analysis_result import PeAnalysisResult, PeSection

_MAX_SECTIONS = 96
_PE32_MAGIC = 0x10B
_PE32_PLUS_MAGIC = 0x20B
_DLL_CHARACTERISTIC = 0x2000
_SECTION_READABLE = 0x40000000
_SECTION_WRITABLE = 0x80000000
_SECTION_EXECUTABLE = 0x20000000
_MACHINES = {
    0x014C: "x86",
    0x8664: "x86-64",
    0x01C0: "ARM",
    0x01C4: "ARM",
    0xAA64: "ARM64",
}
_SUBSYSTEMS = {
    1: "Native",
    2: "Windows GUI",
    3: "Windows CUI",
    9: "Windows CE GUI",
    10: "EFI Application",
}


class PeAnalyzer:
    """PEヘッダーとセクションテーブルを読み取り専用で解析する。"""

    def analyze(self, file_input: FileInput) -> PeAnalysisResult | None:
        content = file_input.content
        try:
            return self._analyze(content, file_input.size)
        except (OverflowError, struct.error, UnicodeError, ValueError):
            return None

    def _analyze(
        self,
        content: bytes,
        file_size: int,
    ) -> PeAnalysisResult | None:
        if len(content) < 0x40 or content[:2] != b"MZ":
            return None

        pe_offset = struct.unpack_from("<I", content, 0x3C)[0]
        if pe_offset > len(content) - 24:
            return None
        if content[pe_offset : pe_offset + 4] != b"PE\x00\x00":
            return None

        coff_offset = pe_offset + 4
        (
            machine,
            number_of_sections,
            timestamp,
            _,
            _,
            optional_size,
            characteristics,
        ) = struct.unpack_from("<HHIIIHH", content, coff_offset)
        if not 1 <= number_of_sections <= _MAX_SECTIONS:
            return None

        optional_offset = coff_offset + 20
        optional_end = optional_offset + optional_size
        if optional_size < 70 or optional_end > len(content):
            return None

        optional_magic = struct.unpack_from("<H", content, optional_offset)[0]
        if optional_magic == _PE32_MAGIC:
            pe_format = "PE32"
            image_base = struct.unpack_from(
                "<I", content, optional_offset + 28
            )[0]
        elif optional_magic == _PE32_PLUS_MAGIC:
            pe_format = "PE32+"
            image_base = struct.unpack_from(
                "<Q", content, optional_offset + 24
            )[0]
        else:
            return None

        entry_point = struct.unpack_from(
            "<I", content, optional_offset + 16
        )[0]
        section_alignment = struct.unpack_from(
            "<I", content, optional_offset + 32
        )[0]
        file_alignment = struct.unpack_from(
            "<I", content, optional_offset + 36
        )[0]
        subsystem_value = struct.unpack_from(
            "<H", content, optional_offset + 68
        )[0]

        section_table_end = optional_end + number_of_sections * 40
        if section_table_end > len(content):
            return None

        sections: list[PeSection] = []
        for index in range(number_of_sections):
            section_offset = optional_end + index * 40
            raw_name = content[section_offset : section_offset + 8]
            name = raw_name.split(b"\x00", 1)[0].decode("ascii", errors="replace")
            (
                virtual_size,
                virtual_address,
                raw_size,
                raw_offset,
            ) = struct.unpack_from("<IIII", content, section_offset + 8)
            section_characteristics = struct.unpack_from(
                "<I", content, section_offset + 36
            )[0]
            raw_end = raw_offset + raw_size
            sections.append(
                PeSection(
                    name=name,
                    virtual_size=virtual_size,
                    virtual_address=virtual_address,
                    raw_size=raw_size,
                    raw_offset=raw_offset,
                    characteristics=section_characteristics,
                    readable=bool(
                        section_characteristics & _SECTION_READABLE
                    ),
                    writable=bool(
                        section_characteristics & _SECTION_WRITABLE
                    ),
                    executable=bool(
                        section_characteristics & _SECTION_EXECUTABLE
                    ),
                    raw_data_in_bounds=(
                        raw_size == 0
                        or raw_offset <= file_size
                        and raw_end <= file_size
                    ),
                )
            )

        return PeAnalysisResult(
            valid_signature=True,
            format=pe_format,
            architecture=_MACHINES.get(machine, "unknown"),
            number_of_sections=number_of_sections,
            timestamp=timestamp,
            entry_point_rva=entry_point,
            image_base=image_base,
            section_alignment=section_alignment,
            file_alignment=file_alignment,
            subsystem=_SUBSYSTEMS.get(
                subsystem_value,
                f"unknown ({subsystem_value})",
            ),
            kind="DLL" if characteristics & _DLL_CHARACTERISTIC else "EXE",
            sections=tuple(sections),
        )
