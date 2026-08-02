from app.challenge.challenge_input import ChallengeInput
from app.file.pe_analysis_result import PeAnalysisResult

_TEXT_CONTENT_LIMIT = 10_000
_STRINGS_CONTEXT_LIMIT = 50


class ChallengeContextBuilder:
    """ChallengeInput を AI 推論用コンテキスト文字列へ整形するビルダー。"""

    def build(self, challenge: ChallengeInput) -> str:
        question = challenge.question.strip() if challenge.question else ""
        if not question:
            raise ValueError("Challenge question cannot be empty.")

        lines = [
            "問題文：",
            question,
            "",
            "添付ファイル：",
        ]

        if not challenge.files:
            lines.append("なし")
            return "\n".join(lines)

        for index, file_res in enumerate(challenge.files, start=1):
            lines.append(f"\n[ファイル {index}]")
            lines.append(f"ファイル名：{file_res.name}")
            lines.append(f"検出形式：{file_res.detected_type}")
            lines.append(f"サイズ：{file_res.size} bytes")
            lines.append(f"拡張子：{file_res.extension}")

            lines.append("\nテキスト内容：")
            if file_res.text_content is None:
                lines.append("利用できません")
            else:
                text = file_res.text_content
                if len(text) > _TEXT_CONTENT_LIMIT:
                    text = text[:_TEXT_CONTENT_LIMIT] + "\n[省略]"
                lines.append(text)

            lines.append("\n抽出文字列：")
            if not file_res.strings:
                lines.append("なし")
            else:
                limited_strings = file_res.strings[:_STRINGS_CONTEXT_LIMIT]
                for s in limited_strings:
                    lines.append(f"- {s}")

            if file_res.pe_info is not None:
                self._append_pe_info(lines, file_res.pe_info)

        return "\n".join(lines)

    def _append_pe_info(
        self,
        lines: list[str],
        pe_info: PeAnalysisResult,
    ) -> None:
        lines.append("\nPE解析：")
        lines.append(f"- 形式：{pe_info.format}")
        lines.append(f"- アーキテクチャ：{pe_info.architecture}")
        lines.append(f"- セクション数：{pe_info.number_of_sections}")
        lines.append(f"- TimeDateStamp：0x{pe_info.timestamp:X}")
        lines.append(f"- EntryPoint RVA：0x{pe_info.entry_point_rva:X}")
        lines.append(f"- ImageBase：0x{pe_info.image_base:X}")
        lines.append(f"- SectionAlignment：0x{pe_info.section_alignment:X}")
        lines.append(f"- FileAlignment：0x{pe_info.file_alignment:X}")
        lines.append(f"- Subsystem：{pe_info.subsystem}")
        lines.append(f"- 種別：{pe_info.kind}")
        lines.append("\nセクション：")
        for section in pe_info.sections:
            permissions = "".join(
                permission
                for enabled, permission in (
                    (section.readable, "R"),
                    (section.writable, "W"),
                    (section.executable, "X"),
                )
                if enabled
            ) or "-"
            lines.append(
                f"- {section.name or '(名前なし)'} "
                f"RVA=0x{section.virtual_address:X} "
                f"VirtualSize=0x{section.virtual_size:X} "
                f"RawSize=0x{section.raw_size:X} "
                f"RawOffset=0x{section.raw_offset:X} "
                f"Characteristics=0x{section.characteristics:X} "
                f"{permissions}"
            )
