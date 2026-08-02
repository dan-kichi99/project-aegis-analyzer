from dataclasses import dataclass

from app.file.appended_data_result import AppendedDataResult
from app.file.elf_analysis_result import ElfAnalysisResult
from app.file.pe_analysis_result import PeAnalysisResult
from app.file.rev_clue_result import RevClueResult
from app.solver.caesar_result import CaesarResult
from app.solver.xor_result import SingleByteXorResult


@dataclass(slots=True)
class FileAnalysisResult:
    """ローカルファイルから抽出された安全な静的特徴を保持する DTO。"""

    name: str
    size: int
    extension: str
    detected_type: str
    text_content: str | None
    strings: list[str]
    pe_info: PeAnalysisResult | None = None
    elf_info: ElfAnalysisResult | None = None
    rev_clues: RevClueResult | None = None
    xor_result: SingleByteXorResult | None = None
    caesar_result: CaesarResult | None = None
    appended_data: AppendedDataResult | None = None
