from dataclasses import dataclass

MAX_BINWALK_DESCRIPTION_CHARACTERS = 500
MAX_BINWALK_ENTRIES = 100


@dataclass(slots=True, frozen=True)
class BinwalkEntry:
    decimal_offset: int
    hexadecimal_offset: str
    description: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.decimal_offset, int)
            or isinstance(self.decimal_offset, bool)
            or self.decimal_offset < 0
        ):
            raise ValueError("decimal_offsetは0以上の整数で指定してください。")
        if not self.hexadecimal_offset:
            raise ValueError("hexadecimal_offsetは空にできません。")
        if len(self.description) > MAX_BINWALK_DESCRIPTION_CHARACTERS:
            raise ValueError("descriptionは500文字以内で指定してください。")


@dataclass(slots=True, frozen=True)
class BinwalkAnalysis:
    entries: tuple[BinwalkEntry, ...]
    parsed: bool
    truncated: bool

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple):
            raise ValueError(  # noqa: TRY004 - DTO入力違反はValueErrorへ統一
                "entriesはtupleで指定してください。"
            )
        if len(self.entries) > MAX_BINWALK_ENTRIES:
            raise ValueError("entriesは最大100件です。")
