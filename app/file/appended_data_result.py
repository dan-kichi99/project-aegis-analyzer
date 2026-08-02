from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class AppendedDataResult:
    container_type: str
    end_offset: int
    appended_offset: int
    appended_size: int
    detected_type: str
    signature: str
    preview: str | None
    content: bytes | None
