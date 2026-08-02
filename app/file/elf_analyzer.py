import struct

from app.file.elf_analysis_result import (
    ElfAnalysisResult,
    ElfSection,
    ElfSegment,
)
from app.file.file_input import FileInput

_MAX_PROGRAM_HEADERS = 128
_MAX_SECTION_HEADERS = 256
_MACHINES = {
    3: "x86",
    8: "MIPS",
    40: "ARM",
    62: "x86-64",
    183: "ARM64",
    243: "RISC-V",
}
_FILE_TYPES = {
    1: "Relocatable",
    2: "Executable",
    3: "Shared Object / PIE候補",
    4: "Core",
}
_SEGMENT_TYPES = {
    0: "PT_NULL",
    1: "PT_LOAD",
    2: "PT_DYNAMIC",
    3: "PT_INTERP",
    4: "PT_NOTE",
    6: "PT_PHDR",
    7: "PT_TLS",
}
_SECTION_TYPES = {
    0: "SHT_NULL",
    1: "SHT_PROGBITS",
    2: "SHT_SYMTAB",
    3: "SHT_STRTAB",
    4: "SHT_RELA",
    6: "SHT_DYNAMIC",
    7: "SHT_NOTE",
    8: "SHT_NOBITS",
    11: "SHT_DYNSYM",
}


class ElfAnalyzer:
    """ELF Header・Program Header・Section Headerを静的解析する。"""

    def analyze(self, file_input: FileInput) -> ElfAnalysisResult | None:
        try:
            return self._analyze(file_input.content, file_input.size)
        except (OverflowError, struct.error, UnicodeError, ValueError):
            return None

    def _analyze(
        self,
        content: bytes,
        file_size: int,
    ) -> ElfAnalysisResult | None:
        available_size = min(file_size, len(content))
        if len(content) < 16 or content[:4] != b"\x7fELF":
            return None
        elf_class_value = content[4]
        data_encoding = content[5]
        if elf_class_value not in (1, 2) or data_encoding not in (1, 2):
            return None
        endian = "<" if data_encoding == 1 else ">"
        endianness = "little-endian" if data_encoding == 1 else "big-endian"

        if elf_class_value == 1:
            header_format = f"{endian}HHIIIIIHHHHHH"
            expected_header_size = 52
            expected_program_size = 32
            expected_section_size = 40
            elf_class = "ELF32"
        else:
            header_format = f"{endian}HHIQQQIHHHHHH"
            expected_header_size = 64
            expected_program_size = 56
            expected_section_size = 64
            elf_class = "ELF64"
        if len(content) < expected_header_size:
            return None

        (
            file_type_value,
            machine,
            _,
            entry_point,
            program_offset,
            section_offset,
            flags,
            header_size,
            program_entry_size,
            program_count,
            section_entry_size,
            section_count,
            section_name_index,
        ) = struct.unpack_from(header_format, content, 16)
        if header_size < expected_header_size:
            return None
        if program_count > _MAX_PROGRAM_HEADERS:
            return None
        if section_count > _MAX_SECTION_HEADERS:
            return None
        if program_count and program_entry_size < expected_program_size:
            return None
        if section_count and section_entry_size < expected_section_size:
            return None
        if not self._table_in_bounds(
            program_offset,
            program_entry_size,
            program_count,
            len(content),
        ):
            return None
        if not self._table_in_bounds(
            section_offset,
            section_entry_size,
            section_count,
            len(content),
        ):
            return None

        segments, interpreter = self._read_segments(
            content,
            available_size,
            elf_class_value,
            endian,
            program_offset,
            program_entry_size,
            program_count,
        )
        section_records = self._read_section_records(
            content,
            elf_class_value,
            endian,
            section_offset,
            section_entry_size,
            section_count,
        )
        names = self._read_section_names(
            content,
            section_records,
            section_name_index,
        )
        sections = tuple(
            self._make_section(record, names[index], available_size)
            for index, record in enumerate(section_records)
        )
        return ElfAnalysisResult(
            valid_signature=True,
            elf_class=elf_class,
            endianness=endianness,
            architecture=_MACHINES.get(machine, "unknown"),
            file_type=_FILE_TYPES.get(file_type_value, "Unknown"),
            entry_point=entry_point,
            program_header_offset=program_offset,
            section_header_offset=section_offset,
            program_header_count=program_count,
            section_header_count=section_count,
            flags=flags,
            interpreter=interpreter,
            sections=sections,
            segments=segments,
        )

    def _table_in_bounds(
        self,
        offset: int,
        entry_size: int,
        count: int,
        content_size: int,
    ) -> bool:
        if count == 0:
            return True
        return offset <= content_size and offset + entry_size * count <= content_size

    def _read_segments(
        self,
        content: bytes,
        file_size: int,
        elf_class: int,
        endian: str,
        offset: int,
        entry_size: int,
        count: int,
    ) -> tuple[tuple[ElfSegment, ...], str | None]:
        segments: list[ElfSegment] = []
        interpreter: str | None = None
        for index in range(count):
            start = offset + index * entry_size
            if elf_class == 1:
                values = struct.unpack_from(f"{endian}IIIIIIII", content, start)
                segment_type, file_offset, va, _, file_data_size, memory_size, flags, alignment = values
            else:
                values = struct.unpack_from(f"{endian}IIQQQQQQ", content, start)
                segment_type, flags, file_offset, va, _, file_data_size, memory_size, alignment = values
            in_bounds = file_data_size == 0 or (
                file_offset <= file_size
                and file_offset + file_data_size <= file_size
            )
            if segment_type == 3 and in_bounds and file_data_size:
                raw = content[file_offset : file_offset + file_data_size]
                try:
                    decoded = raw.split(b"\x00", 1)[0].decode("utf-8")
                except UnicodeDecodeError:
                    decoded = ""
                if decoded:
                    interpreter = decoded
            segments.append(
                ElfSegment(
                    segment_type=_SEGMENT_TYPES.get(
                        segment_type, f"unknown ({segment_type})"
                    ),
                    file_offset=file_offset,
                    virtual_address=va,
                    file_size=file_data_size,
                    memory_size=memory_size,
                    flags=flags,
                    alignment=alignment,
                    readable=bool(flags & 4),
                    writable=bool(flags & 2),
                    executable=bool(flags & 1),
                    data_in_bounds=in_bounds,
                )
            )
        return tuple(segments), interpreter

    def _read_section_records(
        self,
        content: bytes,
        elf_class: int,
        endian: str,
        offset: int,
        entry_size: int,
        count: int,
    ) -> list[tuple[int, int, int, int, int, int]]:
        records = []
        for index in range(count):
            start = offset + index * entry_size
            if elf_class == 1:
                values = struct.unpack_from(f"{endian}IIIIIIIIII", content, start)
                name, section_type, flags, va, file_offset, size = values[:6]
            else:
                values = struct.unpack_from(f"{endian}IIQQQQIIQQ", content, start)
                name, section_type, flags, va, file_offset, size = values[:6]
            records.append((name, section_type, flags, va, file_offset, size))
        return records

    def _read_section_names(
        self,
        content: bytes,
        records: list[tuple[int, int, int, int, int, int]],
        string_table_index: int,
    ) -> list[str]:
        names = [""] * len(records)
        if string_table_index >= len(records):
            return names
        _, section_type, _, _, table_offset, table_size = records[
            string_table_index
        ]
        if (
            section_type != 3
            or table_offset > len(content)
            or table_offset + table_size > len(content)
        ):
            return names
        table = content[table_offset : table_offset + table_size]
        for index, record in enumerate(records):
            name_offset = record[0]
            if name_offset >= len(table):
                continue
            end = table.find(b"\x00", name_offset)
            if end == -1:
                end = len(table)
            names[index] = table[name_offset:end].decode(
                "utf-8", errors="replace"
            )
        return names

    def _make_section(
        self,
        record: tuple[int, int, int, int, int, int],
        name: str,
        file_size: int,
    ) -> ElfSection:
        _, section_type, flags, va, file_offset, size = record
        in_bounds = section_type == 8 or size == 0 or (
            file_offset <= file_size and file_offset + size <= file_size
        )
        return ElfSection(
            name=name,
            section_type=_SECTION_TYPES.get(
                section_type, f"unknown ({section_type})"
            ),
            flags=flags,
            virtual_address=va,
            file_offset=file_offset,
            size=size,
            executable=bool(flags & 4),
            writable=bool(flags & 1),
            allocatable=bool(flags & 2),
            data_in_bounds=in_bounds,
        )
