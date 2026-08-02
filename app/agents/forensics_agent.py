import re

from app.agents.agent import BaseAgent
from app.agents.agent_input import AgentInput
from app.agents.agent_result import AgentEvidence, AgentResult, AgentStatus, AgentType
from app.analyzer.analyzer import Category
from app.client.base_client import BaseAIClient
from app.judge.flag_extractor import FlagExtractor
from app.prompt.prompt_manager import PromptManager

MAX_CONTEXT_CHARACTERS = 20_000
MAX_KNOWLEDGE_ITEMS = 10
MAX_KNOWLEDGE_ITEM_CHARACTERS = 2_000
MAX_KNOWLEDGE_TOTAL_CHARACTERS = 10_000
MAX_EVIDENCE_ITEMS = 20
MAX_EVIDENCE_DETAIL_CHARACTERS = 500
MAX_SUMMARY_CHARACTERS = 500
MAX_FILES = 20
MAX_ZIP_ENTRIES = 20
MAX_IMPORTANT_STRINGS = 10
MAX_IMPORTANT_STRING_CHARACTERS = 300
_CLUES = (
    "file signature", "magic bytes", "mbr", "gpt", "ntfs", "fat", "ext4",
    "deleted", "unallocated", "slack space", "pcap", "pcapng", "wireshark",
    "tcp", "udp", "dns", "packet", "stream", "follow tcp stream",
    "steganography", "steg", "lsb", "exif", "metadata", "hidden", "embedded",
    "alpha channel", "pixel", "palette", "zip", "gzip", "7z", "rar",
    "password protected", "archive", "compressed", "memory dump", "registry",
    "event log", "browser history", "timestamp", "timezone",
)
_IMPORTANT = re.compile(
    r"password|secret|key|https?://|(?:\b\d{1,3}\.){3}\d{1,3}\b|metadata|"
    r"comment|author|hidden|embedded|steg|pcap|packet|stream|timestamp|timezone|"
    r"(?:[A-Za-z0-9+/]{8,}={0,2})|(?:\b[0-9a-fA-F]{8,}\b)|"
    r"\b[^\s]+\.(?:png|jpe?g|zip|pdf|pcapng?|txt|bin|exe|elf)\b",
    re.IGNORECASE,
)
_EXTENSION_TYPES = {
    ".txt": {"text"}, ".png": {"png"}, ".jpg": {"jpeg"}, ".jpeg": {"jpeg"},
    ".zip": {"zip"}, ".pdf": {"pdf"}, ".exe": {"pe"}, ".elf": {"elf"},
}


class ForensicsAgent(BaseAgent):
    """既存ファイル解析結果だけを整理するForensics/Misc専門Agent。"""

    def __init__(self, ai_client: BaseAIClient, flag_extractor: FlagExtractor | None = None, prompt_manager: PromptManager | None = None) -> None:
        self._ai_client = ai_client
        self._flag_extractor = flag_extractor or FlagExtractor()
        self._prompt_manager = prompt_manager or PromptManager()

    @property
    def agent_type(self) -> AgentType:
        return AgentType.FORENSICS

    def with_ai_client(self, ai_client: BaseAIClient) -> "ForensicsAgent":
        return ForensicsAgent(ai_client, self._flag_extractor, self._prompt_manager)

    def analyze(self, agent_input: AgentInput) -> AgentResult:
        matches_target = (
            agent_input.target_agent is self.agent_type
            if agent_input.target_agent is not None
            else agent_input.category.casefold()
            in {Category.MISC.casefold(), "forensics"}
        )
        if not matches_target:
            return AgentResult(self.agent_type, AgentStatus.SKIPPED, f"カテゴリ「{agent_input.category}」はForensics対象外です。", None, None, None, (), (), None)
        evidence = self._evidence(agent_input)
        flags = self._flags(agent_input)
        if flags:
            return AgentResult(self.agent_type, AgentStatus.COMPLETED, "添付ファイルからFlag候補を検出しました。", "候補を問題内容と手動で照合してください。", flags[0], 90, tuple(evidence), ("Flag候補を問題内容と手動で照合する",), None)
        response = self._ai_client.generate(self._prompt(agent_input, evidence))
        ai_flag = self._flag_extractor.extract(response)
        evidence = evidence[: MAX_EVIDENCE_ITEMS - 1]
        evidence.append(AgentEvidence("ai_analysis", self._limit(response), 60 if ai_flag else 40))
        return AgentResult(self.agent_type, AgentStatus.COMPLETED, response[:MAX_SUMMARY_CHARACTERS], response, ai_flag, 60 if ai_flag else 40, tuple(evidence), ("重要なファイル・offset・metadataを手動確認する",), None)

    def _evidence(self, agent_input: AgentInput) -> list[AgentEvidence]:
        buckets: list[list[AgentEvidence]] = [[] for _ in range(8)]
        seen: set[tuple[str, str]] = set()
        zip_entries: dict[str, list] = {}
        important_count = 0
        for file_result in agent_input.challenge.files:
            values = [file_result.text_content or "", *file_result.strings]
            for value in values:
                for flag in self._flag_extractor.extract_all(value):
                    self._add(buckets[0], seen, "local_flag_candidate", f"{file_result.name}: {flag}", 90)
            if file_result.appended_data is not None:
                item = file_result.appended_data
                self._add(buckets[1], seen, "appended_data", f"{file_result.name}: container={item.container_type}, end_offset={item.end_offset}, appended_offset={item.appended_offset}, size={item.appended_size}, detected_type={item.detected_type}, signature={item.signature}, preview={(item.preview or '')[:200]}", 80)
            if "::" in file_result.name:
                archive, _ = file_result.name.split("::", 1)
                zip_entries.setdefault(archive, []).append(file_result)
            mismatch = self._mismatch(file_result.extension, file_result.detected_type)
            if mismatch:
                self._add(buckets[3], seen, "format_mismatch", f"{file_result.name}: 拡張子={file_result.extension}、検出形式={file_result.detected_type}。形式が異なる可能性があります。", 70)
            for value in file_result.strings:
                lower = value.casefold()
                if any(clue in lower for clue in _CLUES):
                    self._add(buckets[5], seen, "forensics_clue", f"{file_result.name}: {value}", 55)
                if important_count < MAX_IMPORTANT_STRINGS and (self._flag_extractor.extract(value) or _IMPORTANT.search(value)):
                    before = len(buckets[6])
                    self._add(buckets[6], seen, "important_string", value[:MAX_IMPORTANT_STRING_CHARACTERS], 70 if any(word in lower for word in ("metadata", "exif", "comment", "author")) else 55)
                    if len(buckets[6]) > before:
                        important_count += 1
            if len(buckets[7]) < MAX_FILES:
                note = ""
                if file_result.size == 0:
                    note = "、0 byteファイル"
                elif file_result.size < 16:
                    note = "、非常に小さいファイル"
                self._add(buckets[7], seen, "file_info", f"{file_result.name}: 拡張子={file_result.extension}、検出形式={file_result.detected_type}、サイズ={file_result.size} bytes{note}", 35)
        for archive, entries in zip_entries.items():
            details = "; ".join(f"{entry.name.split('::', 1)[1]} ({entry.detected_type})" for entry in entries[:MAX_ZIP_ENTRIES])
            self._add(buckets[2], seen, "zip_structure", f"{archive}: 内部ファイル数={len(entries)}、内部ファイル={details}", 80)
        return [item for bucket in buckets for item in bucket][:MAX_EVIDENCE_ITEMS]

    def _flags(self, agent_input: AgentInput) -> list[str]:
        flags: list[str] = []
        for file_result in agent_input.challenge.files:
            flags.extend(self._flag_extractor.extract_all(file_result.text_content or ""))
            for value in file_result.strings:
                flags.extend(self._flag_extractor.extract_all(value))
            if file_result.appended_data is not None:
                item = file_result.appended_data
                flags.extend(self._flag_extractor.extract_all(item.preview or ""))
                flags.extend(self._flag_extractor.extract_all((item.content or b"").decode("utf-8", errors="replace")))
        return list(dict.fromkeys(flags))

    def _mismatch(self, extension: str, detected_type: str) -> bool:
        expected = _EXTENSION_TYPES.get(extension.casefold())
        return expected is not None and detected_type.casefold() not in expected

    def _add(self, bucket: list[AgentEvidence], seen: set[tuple[str, str]], source: str, detail: str, confidence: int) -> None:
        detail = self._limit(detail)
        key = (source, detail.casefold())
        if key not in seen:
            seen.add(key)
            bucket.append(AgentEvidence(source, detail, confidence))

    def _prompt(self, agent_input: AgentInput, evidence: list[AgentEvidence]) -> str:
        evidence_text = "\n".join(f"- [{item.source}] {item.detail}" for item in evidence) or "- ファイルEvidenceはありません。"
        question = (
            "Digital Forensics / Misc CTF専門家として提供済み静的情報を分析してください。\n"
            "確定事実と仮説を区別し、Flag候補を正解と断定しないでください。\n"
            "次に手動確認するファイル・offset・metadataを具体化してください。\n"
            "外部ツールを自動実行せず、ファイルを実行しないでください。\n"
            "パス、offset、signature、ファイル名を改変しないでください。\n\n"
            f"問題コンテキスト:\n{agent_input.context[:MAX_CONTEXT_CHARACTERS]}\n\n"
            f"既存ファイルEvidence:\n{evidence_text}"
        )
        return self._prompt_manager.build(question, Category.MISC, self._knowledge(agent_input.local_knowledge))

    def _knowledge(self, knowledge: tuple[str, ...]) -> list[str]:
        result: list[str] = []
        total = 0
        for item in knowledge[:MAX_KNOWLEDGE_ITEMS]:
            remaining = MAX_KNOWLEDGE_TOTAL_CHARACTERS - total
            if remaining <= 0:
                break
            value = item[: min(MAX_KNOWLEDGE_ITEM_CHARACTERS, remaining)]
            result.append(value)
            total += len(value)
        return result

    def _limit(self, value: str) -> str:
        return value[:MAX_EVIDENCE_DETAIL_CHARACTERS]
