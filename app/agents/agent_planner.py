from app.agents.agent_input import AgentInput
from app.agents.agent_plan import AgentCandidate, AgentExecutionPlan
from app.agents.agent_result import AgentType
from app.agents.agent_router import category_to_agent_type
from app.file.file_analysis_result import FileAnalysisResult

MAX_AGENT_CANDIDATES = 3


class AgentPlanner:
    """構造化済み解析結果から、実行を伴わずAgent候補を計画する。"""

    def plan(self, agent_input: AgentInput) -> AgentExecutionPlan:
        primary_type = category_to_agent_type(agent_input.category)
        candidates = {
            primary_type: AgentCandidate(
                primary_type,
                100,
                f"Analyzerカテゴリ「{agent_input.category}」に対応する主担当です。",
                True,
            )
        }
        challenge = agent_input.challenge

        if challenge.rsa_result is not None:
            self._add(candidates, AgentType.CRYPTO, 80, "RSA解析結果があります。")
        if any(file.xor_result and file.xor_result.candidates for file in challenge.files):
            self._add(candidates, AgentType.CRYPTO, 80, "XOR解析候補があります。")
        if any(file.caesar_result and file.caesar_result.candidates for file in challenge.files):
            self._add(candidates, AgentType.CRYPTO, 80, "Caesar解析候補があります。")

        if any(file.pe_info is not None for file in challenge.files):
            self._add(candidates, AgentType.REV, 80, "PE解析結果があります。")
        if any(file.elf_info is not None for file in challenge.files):
            self._add(candidates, AgentType.REV, 80, "ELF解析結果があります。")
        if any(file.rev_clues and file.rev_clues.clues for file in challenge.files):
            self._add(candidates, AgentType.REV, 80, "Rev手掛かりがあります。")

        for file in challenge.files:
            forensics = self._forensics_reason(file)
            if forensics is not None:
                priority, reason = forensics
                self._add(candidates, AgentType.FORENSICS, priority, reason)
        if len(challenge.files) > 1:
            self._add(
                candidates,
                AgentType.FORENSICS,
                50,
                "複数の添付ファイルがあります。",
            )

        ordered = sorted(
            candidates.values(),
            key=lambda item: (not item.primary, -item.priority, item.agent_type.value),
        )
        return AgentExecutionPlan(
            category=agent_input.category,
            candidates=tuple(ordered[:MAX_AGENT_CANDIDATES]),
        )

    def _add(
        self,
        candidates: dict[AgentType, AgentCandidate],
        agent_type: AgentType,
        priority: int,
        reason: str,
    ) -> None:
        current = candidates.get(agent_type)
        if current is None or (not current.primary and priority > current.priority):
            candidates[agent_type] = AgentCandidate(agent_type, priority, reason, False)

    def _forensics_reason(
        self,
        file: FileAnalysisResult,
    ) -> tuple[int, str] | None:
        detected = file.detected_type.casefold()
        if "::" in file.name or detected == "zip":
            return 80, "ZIP構造化解析結果があります。"
        if file.appended_data is not None:
            return 80, "ファイル末尾追加データがあります。"
        if detected in {"png", "jpeg", "jpg", "pdf", "unknown"}:
            return 70, f"Forensics対象形式「{file.detected_type}」です。"
        extension = file.extension.casefold().removeprefix(".")
        normalized = {
            "dll": "pe",
            "exe": "pe",
            "jpg": "jpeg",
            "txt": "text",
        }
        if normalized.get(extension, extension) != normalized.get(detected, detected):
            return 70, "拡張子と検出形式が一致しません。"
        return None
