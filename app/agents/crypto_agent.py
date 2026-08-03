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
from app.judge.flag_extractor import FlagExtractor
from app.prompt.prompt_manager import PromptManager

MAX_CONTEXT_CHARACTERS = 20_000
MAX_KNOWLEDGE_ITEMS = 10
MAX_KNOWLEDGE_ITEM_CHARACTERS = 2_000
MAX_KNOWLEDGE_TOTAL_CHARACTERS = 10_000
MAX_EVIDENCE_ITEMS = 20
MAX_EVIDENCE_DETAIL_CHARACTERS = 500
MAX_SUMMARY_CHARACTERS = 500


class CryptoAgent(BaseAgent):
    """既存ローカル解析を優先し、不足時だけAIを1回使うCrypto専門Agent。"""

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
        return AgentType.CRYPTO

    def with_ai_client(self, ai_client: BaseAIClient) -> "CryptoAgent":
        return CryptoAgent(ai_client, self._flag_extractor, self._prompt_manager)

    def analyze(self, agent_input: AgentInput) -> AgentResult:
        matches_target = (
            agent_input.target_agent is self.agent_type
            if agent_input.target_agent is not None
            else agent_input.category.casefold() == Category.CRYPTO.casefold()
        )
        if not matches_target:
            return AgentResult(
                agent_type=self.agent_type,
                status=AgentStatus.SKIPPED,
                summary=f"カテゴリ「{agent_input.category}」はCrypto対象外です。",
                answer=None,
                flag_candidate=None,
                confidence=None,
                evidence=(),
                next_actions=(),
                error_message=None,
            )

        evidence, local_flags = self._local_analysis(agent_input)
        if local_flags:
            return AgentResult(
                agent_type=self.agent_type,
                status=AgentStatus.COMPLETED,
                summary="既存のローカル暗号解析からFlag候補を検出しました。",
                answer="ローカル解析結果を問題内容と照合してください。",
                flag_candidate=local_flags[0],
                confidence=90,
                evidence=tuple(evidence[:MAX_EVIDENCE_ITEMS]),
                next_actions=("Flag候補を問題内容と手動で照合する",),
                error_message=None,
            )

        prompt = self._build_prompt(agent_input, evidence)
        response = self._ai_client.generate(prompt)
        ai_flag = self._flag_extractor.extract(response)
        limited_evidence = evidence[: MAX_EVIDENCE_ITEMS - 1]
        limited_evidence.append(
            AgentEvidence(
                source="ai_analysis",
                detail=self._limit(response),
                confidence=60 if ai_flag else 40,
            )
        )
        return AgentResult(
            agent_type=self.agent_type,
            status=AgentStatus.COMPLETED,
            summary=response[:MAX_SUMMARY_CHARACTERS],
            answer=response,
            flag_candidate=ai_flag,
            confidence=60 if ai_flag else 40,
            evidence=tuple(limited_evidence),
            next_actions=("AI分析の確定事実と仮説を手動で検証する",),
            error_message=None,
        )

    def _local_analysis(
        self,
        agent_input: AgentInput,
    ) -> tuple[list[AgentEvidence], list[str]]:
        evidence: list[AgentEvidence] = []
        rsa_flags: list[str] = []
        xor_flags: list[str] = []
        caesar_flags: list[str] = []
        challenge = agent_input.challenge

        if challenge.rsa_result is not None:
            rsa = challenge.rsa_result
            parameters = rsa.parameters
            self._append_evidence(
                evidence,
                "rsa_parameters",
                "RSAパラメータ: "
                f"n={parameters.n}, e={parameters.e}, c={parameters.c}, "
                f"p={parameters.p}, q={parameters.q}, d={parameters.d}, "
                f"source={parameters.source}",
                90 if rsa.contains_flag else 70,
            )
            for attempt in rsa.attempts:
                self._append_evidence(
                    evidence,
                    "rsa_attempt",
                    f"method={attempt.method}, success={attempt.success}, "
                    f"plaintext={attempt.plaintext}, detail={attempt.detail}, "
                    f"contains_flag={attempt.contains_flag}",
                    90 if attempt.contains_flag else 70,
                )
            rsa_flags.extend(self._flags(rsa.plaintext))

        for file_result in challenge.files:
            recursive = file_result.recursive_encoding_result
            if recursive is not None:
                for step in recursive.steps[:MAX_EVIDENCE_ITEMS]:
                    self._append_evidence(
                        evidence,
                        f"recursive_encoding:{file_result.name}",
                        (
                            f"method={step.method}, depth={step.depth}, "
                            f"shift={step.caesar_shift}, "
                            f"output={step.output_preview}, "
                            f"flag_candidate={step.flag_candidate}"
                        ),
                        90 if step.flag_candidate else 60,
                    )
            if file_result.text_content:
                self._append_evidence(
                    evidence,
                    f"text:{file_result.name}",
                    f"text_content={file_result.text_content}",
                    50,
                )
            if file_result.strings:
                self._append_evidence(
                    evidence,
                    f"strings:{file_result.name}",
                    f"strings={file_result.strings}",
                    50,
                )
            if file_result.xor_result is not None:
                for candidate in file_result.xor_result.candidates:
                    self._append_evidence(
                        evidence,
                        f"xor:{file_result.name}",
                        f"key={candidate.key}, score={candidate.score}, "
                        f"source={candidate.source}, plaintext={candidate.plaintext}, "
                        f"contains_flag={candidate.contains_flag}",
                        90 if candidate.contains_flag else 60,
                    )
                    xor_flags.extend(self._flags(candidate.plaintext))
            if file_result.caesar_result is not None:
                for candidate in file_result.caesar_result.candidates:
                    self._append_evidence(
                        evidence,
                        f"caesar:{file_result.name}",
                        f"shift={candidate.shift}, score={candidate.score}, "
                        f"source={candidate.source}, plaintext={candidate.plaintext}, "
                        f"contains_flag={candidate.contains_flag}",
                        90 if candidate.contains_flag else 60,
                    )
                    caesar_flags.extend(self._flags(candidate.plaintext))

        return evidence, self._unique((*rsa_flags, *xor_flags, *caesar_flags))

    def _build_prompt(
        self,
        agent_input: AgentInput,
        evidence: list[AgentEvidence],
    ) -> str:
        context = agent_input.context[:MAX_CONTEXT_CHARACTERS]
        evidence_text = "\n".join(
            f"- [{item.source}] {item.detail}" for item in evidence[:MAX_EVIDENCE_ITEMS]
        ) or "- 既存のRSA/XOR/Caesar解析結果はありません。"
        question = (
            "Crypto専門家として、次のコンテキストと既存解析結果を分析してください。\n"
            "確定事実と仮説を明確に区別し、Flag候補を正解と断定しないでください。\n"
            "必要なら検証手順を示し、コード・数式・暗号パラメータを改変しないでください。\n\n"
            f"問題コンテキスト:\n{context}\n\n"
            f"既存ローカル解析結果:\n{evidence_text}"
        )
        return self._prompt_manager.build(
            question=question,
            category=Category.CRYPTO,
            knowledge=self._limited_knowledge(agent_input.local_knowledge),
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

    def _append_evidence(
        self,
        evidence: list[AgentEvidence],
        source: str,
        detail: str,
        confidence: int,
    ) -> None:
        if len(evidence) < MAX_EVIDENCE_ITEMS:
            evidence.append(AgentEvidence(source, self._limit(detail), confidence))

    def _flags(self, text: str | None) -> tuple[str, ...]:
        return self._flag_extractor.extract_all(text or "")

    def _unique(self, values: tuple[str, ...]) -> list[str]:
        return list(dict.fromkeys(values))

    def _limit(self, text: str) -> str:
        return text[:MAX_EVIDENCE_DETAIL_CHARACTERS]
