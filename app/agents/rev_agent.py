import re

from app.agents.agent import BaseAgent
from app.agents.agent_input import AgentInput
from app.agents.agent_result import (
    AgentEvidence,
    AgentResult,
    AgentStatus,
    AgentType,
)
from app.analyzer.analyzer import Category
from app.client.base_client import BaseAIClient
from app.file.file_analysis_result import FileAnalysisResult
from app.judge.flag_extractor import FlagExtractor
from app.prompt.prompt_manager import PromptManager

MAX_CONTEXT_CHARACTERS = 20_000
MAX_KNOWLEDGE_ITEMS = 10
MAX_KNOWLEDGE_ITEM_CHARACTERS = 2_000
MAX_KNOWLEDGE_TOTAL_CHARACTERS = 10_000
MAX_EVIDENCE_ITEMS = 20
MAX_EVIDENCE_DETAIL_CHARACTERS = 500
MAX_SUMMARY_CHARACTERS = 500
MAX_STRUCTURE_ITEMS = 10
MAX_CLUES = 10
MAX_IMPORTANT_STRINGS = 10
MAX_IMPORTANT_STRING_CHARACTERS = 300
_IMPORTANT_STRING_PATTERN = re.compile(
    r"password|secret|key|correct|wrong|success|failed|https?://|"
    r"[A-Za-z]:\\|/(?:[^ /]+/)+|debug|strcmp|"
    r"memcmp|ptrace|IsDebuggerPresent|shell|command|pack|unpack|UPX",
    re.IGNORECASE,
)
_CLUE_CONFIDENCE = {"high": 85, "medium": 65, "low": 40}


class RevAgent(BaseAgent):
    """既存静的構造解析を優先し、不足時だけAIを1回使うRev専門Agent。"""

    def __init__(
        self,
        ai_client: BaseAIClient,
        flag_extractor: FlagExtractor | None = None,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        self._ai_client = ai_client
        self._flag_extractor = flag_extractor or FlagExtractor()
        self._prompt_manager = prompt_manager or PromptManager()

    @property
    def agent_type(self) -> AgentType:
        return AgentType.REV

    def analyze(self, agent_input: AgentInput) -> AgentResult:
        if agent_input.category.casefold() != Category.REV.casefold():
            return AgentResult(
                self.agent_type,
                AgentStatus.SKIPPED,
                f"カテゴリ「{agent_input.category}」はRev対象外です。",
                None,
                None,
                None,
                (),
                (),
                None,
            )

        evidence, flags = self._local_analysis(agent_input)
        if flags:
            return AgentResult(
                self.agent_type,
                AgentStatus.COMPLETED,
                "既存のローカル静的解析からFlag候補を検出しました。",
                "ローカル解析結果を問題内容と照合してください。",
                flags[0],
                90,
                tuple(evidence),
                ("Flag候補を問題内容と手動で照合する",),
                None,
            )

        prompt = self._build_prompt(agent_input, evidence)
        response = self._ai_client.generate(prompt)
        ai_flag = self._flag_extractor.extract(response)
        evidence = evidence[: MAX_EVIDENCE_ITEMS - 1]
        evidence.append(
            AgentEvidence(
                "ai_analysis",
                self._limit(response),
                60 if ai_flag else 40,
            )
        )
        return AgentResult(
            self.agent_type,
            AgentStatus.COMPLETED,
            response[:MAX_SUMMARY_CHARACTERS],
            response,
            ai_flag,
            60 if ai_flag else 40,
            tuple(evidence),
            ("重要な関数・Section・Segmentを静的解析ツールで手動確認する",),
            None,
        )

    def _local_analysis(
        self,
        agent_input: AgentInput,
    ) -> tuple[list[AgentEvidence], list[str]]:
        structural: list[AgentEvidence] = []
        clues: dict[str, list[AgentEvidence]] = {
            "high": [],
            "medium": [],
            "low": [],
        }
        appended: list[AgentEvidence] = []
        important_strings: list[AgentEvidence] = []
        flag_groups: list[list[str]] = [[], [], [], []]
        clue_values: set[str] = set()

        for file_result in agent_input.challenge.files:
            self._pe_evidence(file_result, structural)
            self._elf_evidence(file_result, structural)
            if file_result.rev_clues is not None:
                for clue in file_result.rev_clues.clues:
                    severity = clue.severity.casefold()
                    if severity not in clues:
                        severity = "low"
                    clue_values.add(clue.value)
                    clues[severity].append(
                        AgentEvidence(
                            f"rev_clue:{file_result.name}",
                            self._limit(
                                f"value={clue.value}, category={clue.category}, "
                                f"description={clue.description}, severity={clue.severity}"
                            ),
                            _CLUE_CONFIDENCE[severity],
                        )
                    )
                    flag_groups[0].extend(self._flags(clue.value))
            flag_groups[1].extend(self._flags(file_result.text_content))
            for value in file_result.strings:
                flag_groups[2].extend(self._flags(value))
            self._appended_evidence(file_result, appended, flag_groups[3])
            self._important_string_evidence(
                file_result,
                clue_values,
                important_strings,
            )

        selected_high = clues["high"][:MAX_CLUES]
        remaining = MAX_CLUES - len(selected_high)
        selected_medium = clues["medium"][:remaining]
        remaining -= len(selected_medium)
        selected_low = clues["low"][:remaining]
        ordered = (
            structural
            + selected_high
            + selected_medium
            + appended
            + important_strings
            + selected_low
        )
        flags = self._unique(flag for group in flag_groups for flag in group)
        return ordered[:MAX_EVIDENCE_ITEMS], flags

    def _pe_evidence(
        self,
        file_result: FileAnalysisResult,
        evidence: list[AgentEvidence],
    ) -> None:
        pe = file_result.pe_info
        if pe is None:
            return
        evidence.append(
            AgentEvidence(
                f"pe:{file_result.name}",
                self._limit(
                    f"format={pe.format}, architecture={pe.architecture}, kind={pe.kind}, "
                    f"entry_point_rva={pe.entry_point_rva:#x}, image_base={pe.image_base:#x}, "
                    f"subsystem={pe.subsystem}, section_count={pe.number_of_sections}"
                ),
                75,
            )
        )
        sections = pe.sections[:MAX_STRUCTURE_ITEMS]
        if sections:
            details = "; ".join(
                f"{item.name}[R={item.readable},W={item.writable},X={item.executable},"
                f"raw_in_bounds={item.raw_data_in_bounds}]"
                for item in sections
            )
            evidence.append(
                AgentEvidence(
                    f"pe_sections:{file_result.name}",
                    self._limit(details),
                    85
                    if any(
                        (item.writable and item.executable)
                        or not item.raw_data_in_bounds
                        for item in sections
                    )
                    else 65,
                )
            )

    def _elf_evidence(
        self,
        file_result: FileAnalysisResult,
        evidence: list[AgentEvidence],
    ) -> None:
        elf = file_result.elf_info
        if elf is None:
            return
        evidence.append(
            AgentEvidence(
                f"elf:{file_result.name}",
                self._limit(
                    f"elf_class={elf.elf_class}, endianness={elf.endianness}, "
                    f"architecture={elf.architecture}, file_type={elf.file_type}, "
                    f"entry_point={elf.entry_point:#x}, interpreter={elf.interpreter}, "
                    f"segment_count={elf.program_header_count}, "
                    f"section_count={elf.section_header_count}"
                ),
                75,
            )
        )
        segments = elf.segments[:MAX_STRUCTURE_ITEMS]
        if segments:
            evidence.append(
                AgentEvidence(
                    f"elf_segments:{file_result.name}",
                    self._limit(
                        "; ".join(
                            f"{item.segment_type}[R={item.readable},W={item.writable},"
                            f"X={item.executable},data_in_bounds={item.data_in_bounds}]"
                            for item in segments
                        )
                    ),
                    85
                    if any(
                        (item.writable and item.executable) or not item.data_in_bounds
                        for item in segments
                    )
                    else 65,
                )
            )
        sections = elf.sections[:MAX_STRUCTURE_ITEMS]
        if sections:
            evidence.append(
                AgentEvidence(
                    f"elf_sections:{file_result.name}",
                    self._limit(
                        "; ".join(
                            f"{item.name}[W={item.writable},X={item.executable},"
                            f"data_in_bounds={item.data_in_bounds}]"
                            for item in sections
                        )
                    ),
                    85
                    if any(
                        (item.writable and item.executable) or not item.data_in_bounds
                        for item in sections
                    )
                    else 65,
                )
            )

    def _appended_evidence(
        self,
        file_result: FileAnalysisResult,
        evidence: list[AgentEvidence],
        flags: list[str],
    ) -> None:
        result = file_result.appended_data
        if result is None:
            return
        preview = result.preview
        decoded_content = self._decode_content(result.content)
        evidence.append(
            AgentEvidence(
                f"appended_data:{file_result.name}",
                self._limit(
                    f"container={result.container_type}, offset={result.appended_offset}, "
                    f"size={result.appended_size}, detected_type={result.detected_type}, "
                    f"signature={result.signature}, preview={preview or 'なし'}"
                ),
                70,
            )
        )
        if file_result.pe_info is not None:
            evidence.append(
                AgentEvidence(
                    f"pe_overlay:{file_result.name}",
                    self._limit(
                        f"PE Overlay候補: offset={result.appended_offset}, "
                        f"size={result.appended_size}, type={result.detected_type}"
                    ),
                    70,
                )
            )
        flags.extend(self._flags(preview))
        flags.extend(self._flags(decoded_content))

    def _important_string_evidence(
        self,
        file_result: FileAnalysisResult,
        clue_values: set[str],
        evidence: list[AgentEvidence],
    ) -> None:
        for value in file_result.strings:
            if len(evidence) >= MAX_IMPORTANT_STRINGS:
                break
            if value in clue_values or not (
                self._flags(value) or _IMPORTANT_STRING_PATTERN.search(value)
            ):
                continue
            evidence.append(
                AgentEvidence(
                    f"important_string:{file_result.name}",
                    value[:MAX_IMPORTANT_STRING_CHARACTERS],
                    60,
                )
            )

    def _build_prompt(
        self,
        agent_input: AgentInput,
        evidence: list[AgentEvidence],
    ) -> str:
        evidence_text = "\n".join(
            f"- [{item.source}] {item.detail}" for item in evidence
        ) or "- 既存のPE/ELF/Rev静的解析結果はありません。"
        question = (
            "Reverse Engineering専門家として、次の静的情報を分析してください。\n"
            "確定事実と仮説を区別し、Flag候補を正解と断定しないでください。\n"
            "次に確認すべき関数・Section・Segmentを具体化してください。\n"
            "コード、アドレス、Section名、ファイルパスを改変しないでください。\n\n"
            f"問題コンテキスト:\n{agent_input.context[:MAX_CONTEXT_CHARACTERS]}\n\n"
            f"既存ローカル静的解析:\n{evidence_text}"
        )
        return self._prompt_manager.build(
            question,
            Category.REV,
            self._limited_knowledge(agent_input.local_knowledge),
        )

    def _limited_knowledge(self, knowledge: tuple[str, ...]) -> list[str]:
        limited: list[str] = []
        total = 0
        for item in knowledge[:MAX_KNOWLEDGE_ITEMS]:
            remaining = MAX_KNOWLEDGE_TOTAL_CHARACTERS - total
            if remaining <= 0:
                break
            value = item[: min(MAX_KNOWLEDGE_ITEM_CHARACTERS, remaining)]
            limited.append(value)
            total += len(value)
        return limited

    def _flags(self, text: str | None) -> tuple[str, ...]:
        return self._flag_extractor.extract_all(text or "")

    def _decode_content(self, content: bytes | None) -> str:
        return (content or b"").decode("utf-8", errors="replace")

    def _unique(self, values) -> list[str]:
        return list(dict.fromkeys(values))

    def _limit(self, value: str) -> str:
        return value[:MAX_EVIDENCE_DETAIL_CHARACTERS]
