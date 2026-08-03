from app.challenge.challenge_input import ChallengeInput
from app.file.appended_data_result import AppendedDataResult
from app.file.elf_analysis_result import ElfAnalysisResult
from app.file.pdf_static_analyzer import (
    PDF_FLAG_PREFIX,
    PDF_INFO_PREFIX,
    PDF_METADATA_PREFIX,
    PDF_TRAILING_PREFIX,
    PDF_WARNING_PREFIX,
)
from app.file.pe_analysis_result import PeAnalysisResult
from app.file.png_metadata_analyzer import (
    PNG_FLAG_PREFIX,
    PNG_METADATA_PREFIX,
    PNG_TRAILING_PREFIX,
    PNG_WARNING_PREFIX,
)
from app.file.rev_clue_result import RevClueResult
from app.solver.caesar_result import CaesarResult
from app.solver.recursive_encoding_result import RecursiveEncodingResult
from app.solver.rsa_result import RsaResult
from app.solver.xor_result import SingleByteXorResult

_TEXT_CONTENT_LIMIT = 10_000
_STRINGS_CONTEXT_LIMIT = 50
_ARCHIVE_SUMMARY_PREFIX = "[ARCHIVE_SUMMARY] "
_PNG_RESERVED_PREFIXES = (
    PNG_METADATA_PREFIX,
    PNG_WARNING_PREFIX,
    PNG_TRAILING_PREFIX,
    PNG_FLAG_PREFIX,
)
_PDF_RESERVED_PREFIXES = (
    PDF_METADATA_PREFIX,
    PDF_INFO_PREFIX,
    PDF_WARNING_PREFIX,
    PDF_TRAILING_PREFIX,
    PDF_FLAG_PREFIX,
)
_MAX_PNG_CONTEXT_LINES = 20
_MAX_PDF_CONTEXT_LINES = 20


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
            if challenge.rsa_result is not None:
                self._append_rsa_result(lines, challenge.rsa_result)
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
            display_strings = [
                value
                for value in file_res.strings
                if not value.startswith(_PNG_RESERVED_PREFIXES)
                and not value.startswith(_PDF_RESERVED_PREFIXES)
            ]
            if not display_strings:
                lines.append("なし")
            else:
                limited_strings = display_strings[:_STRINGS_CONTEXT_LIMIT]
                for s in limited_strings:
                    lines.append(f"- {s}")

            archive_summary = [
                value.removeprefix(_ARCHIVE_SUMMARY_PREFIX)
                for value in file_res.strings
                if value.startswith(_ARCHIVE_SUMMARY_PREFIX)
            ]
            if archive_summary:
                lines.append("\nArchive Summary:")
                lines.extend(f"- {value}" for value in archive_summary[:100])

            self._append_png_metadata(lines, file_res.strings)
            self._append_pdf_analysis(lines, file_res.strings)

            if file_res.pe_info is not None:
                self._append_pe_info(lines, file_res.pe_info)
            if file_res.elf_info is not None:
                self._append_elf_info(lines, file_res.elf_info)
            if file_res.rev_clues is not None and file_res.rev_clues.clues:
                self._append_rev_clues(lines, file_res.rev_clues)
            if file_res.xor_result is not None and file_res.xor_result.candidates:
                self._append_xor_candidates(lines, file_res.xor_result)
            if (
                file_res.caesar_result is not None
                and file_res.caesar_result.candidates
            ):
                self._append_caesar_candidates(lines, file_res.caesar_result)
            if file_res.appended_data is not None:
                self._append_appended_data(lines, file_res.appended_data)
            if file_res.recursive_encoding_result is not None:
                self._append_recursive_encoding(
                    lines, file_res.recursive_encoding_result
                )

        if challenge.rsa_result is not None:
            self._append_rsa_result(lines, challenge.rsa_result)

        return "\n".join(lines)

    def _append_recursive_encoding(
        self,
        lines: list[str],
        result: RecursiveEncodingResult,
    ) -> None:
        lines.append("\n再帰エンコード解析：")
        for step in result.steps[:20]:
            shift = (
                f" shift={step.caesar_shift}"
                if step.caesar_shift is not None
                else ""
            )
            flag = (
                f" flag_candidate={step.flag_candidate}"
                if step.flag_candidate is not None
                else ""
            )
            lines.append(
                f'- depth={step.depth} method={step.method}{shift} '
                f'output="{step.output_preview}"{flag}'
            )

    def _append_png_metadata(
        self,
        lines: list[str],
        strings: list[str],
    ) -> None:
        display_lines: list[str] = []
        for value in strings:
            if value.startswith(PNG_METADATA_PREFIX):
                display_lines.append(value.removeprefix(PNG_METADATA_PREFIX))
            elif value.startswith(PNG_WARNING_PREFIX):
                display_lines.append(
                    f"warning={value.removeprefix(PNG_WARNING_PREFIX)}"
                )
            elif value.startswith(PNG_TRAILING_PREFIX):
                display_lines.append(
                    f"trailing_data {value.removeprefix(PNG_TRAILING_PREFIX)}"
                )
        if not display_lines:
            return
        lines.append("\nPNG Metadata:")
        lines.extend(f"- {value}" for value in display_lines[:_MAX_PNG_CONTEXT_LINES])

    def _append_pdf_analysis(
        self,
        lines: list[str],
        strings: list[str],
    ) -> None:
        display_lines: list[str] = []
        for value in strings:
            if value.startswith(PDF_METADATA_PREFIX):
                display_lines.append(value.removeprefix(PDF_METADATA_PREFIX))
            elif value.startswith(PDF_INFO_PREFIX):
                display_lines.append(value.removeprefix(PDF_INFO_PREFIX))
            elif value.startswith(PDF_WARNING_PREFIX):
                display_lines.append(
                    f"warning={value.removeprefix(PDF_WARNING_PREFIX)}"
                )
            elif value.startswith(PDF_TRAILING_PREFIX):
                display_lines.append(
                    f"trailing_data {value.removeprefix(PDF_TRAILING_PREFIX)}"
                )
        if not display_lines:
            return
        lines.append("\nPDF Analysis:")
        lines.extend(f"- {value}" for value in display_lines[:_MAX_PDF_CONTEXT_LINES])

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

    def _append_rev_clues(
        self,
        lines: list[str],
        result: RevClueResult,
    ) -> None:
        severity_labels = {"high": "高", "medium": "中", "low": "低"}
        lines.append("\nRev重要手掛かり：")
        for clue in result.clues:
            severity = severity_labels[clue.severity]
            lines.append(f"- [{severity}] {clue.value}（{clue.category}）")
            lines.append(f"  {clue.description}")

    def _append_xor_candidates(
        self,
        lines: list[str],
        result: SingleByteXorResult,
    ) -> None:
        lines.append("\n単一バイトXOR候補：")
        for candidate in result.candidates:
            plaintext = candidate.plaintext
            if len(plaintext) > 300:
                plaintext = plaintext[:300] + "[省略]"
            lines.append(
                f"- key=0x{candidate.key:02X} score={candidate.score:.4f} "
                f"検出元：{candidate.source}"
            )
            lines.append(f"  {plaintext!r}")

    def _append_caesar_candidates(
        self,
        lines: list[str],
        result: CaesarResult,
    ) -> None:
        lines.append("\nCaesar / ROT候補：")
        for candidate in result.candidates:
            plaintext = candidate.plaintext
            if len(plaintext) > 300:
                plaintext = plaintext[:300] + "[省略]"
            lines.append(
                f"- shift={candidate.shift} score={candidate.score:.4f} "
                f"検出元：{candidate.source}"
            )
            lines.append(f"  {plaintext!r}")

    def _append_rsa_result(
        self,
        lines: list[str],
        result: RsaResult,
    ) -> None:
        parameters = result.parameters
        lines.append("\nRSA診断：")
        lines.append(f"- 検出元：{parameters.source}")
        for name in ("n", "e", "c", "p", "q", "d", "phi"):
            value = getattr(parameters, name)
            if value is not None:
                displayed = str(value)
                if len(displayed) > 200:
                    displayed = displayed[:200] + "[省略]"
                lines.append(f"- {name}：{displayed}")
        for attempt in result.attempts:
            lines.append(f"- 方式：{attempt.method}")
            lines.append(f"- 成否：{'成功' if attempt.success else '失敗'}")
            lines.append(f"- 詳細：{attempt.detail}")
        if result.plaintext is not None:
            plaintext = result.plaintext
            if len(plaintext) > 300:
                plaintext = plaintext[:300] + "[省略]"
            lines.append(f"- 復号結果：{plaintext!r}")
        lines.append(f"- Flag：{'検出' if result.contains_flag else '未検出'}")

    def _append_appended_data(
        self,
        lines: list[str],
        result: AppendedDataResult,
    ) -> None:
        if result.container_type == "pe":
            heading = "末尾追加データ（PE Overlay候補）："
        elif result.container_type == "elf":
            heading = "末尾追加データ（ELF候補）："
        else:
            heading = "末尾追加データ："
        lines.append(f"\n{heading}")
        lines.append(f"- 元形式：{result.container_type.upper()}")
        lines.append(f"- 終端offset：0x{result.end_offset:X}")
        lines.append(f"- 追加offset：0x{result.appended_offset:X}")
        lines.append(f"- サイズ：{result.appended_size} bytes")
        lines.append(f"- 推定形式：{result.detected_type.upper()}")
        lines.append(f"- シグネチャ：{result.signature}")
        if result.preview is not None:
            lines.append(f"- プレビュー：{result.preview!r}")

    def _append_elf_info(
        self,
        lines: list[str],
        elf_info: ElfAnalysisResult,
    ) -> None:
        lines.append("\nELF解析：")
        lines.append(f"- 形式：{elf_info.elf_class}")
        lines.append(f"- エンディアン：{elf_info.endianness}")
        lines.append(f"- アーキテクチャ：{elf_info.architecture}")
        lines.append(f"- 種別：{elf_info.file_type}")
        lines.append(f"- EntryPoint：0x{elf_info.entry_point:X}")
        lines.append(f"- Program Header数：{elf_info.program_header_count}")
        lines.append(f"- Section Header数：{elf_info.section_header_count}")
        if elf_info.interpreter is not None:
            lines.append(f"- Interpreter：{elf_info.interpreter}")

        lines.append("\nセグメント：")
        for segment in elf_info.segments:
            permissions = "".join(
                permission
                for enabled, permission in (
                    (segment.readable, "R"),
                    (segment.writable, "W"),
                    (segment.executable, "X"),
                )
                if enabled
            ) or "-"
            lines.append(
                f"- {segment.segment_type} "
                f"Offset=0x{segment.file_offset:X} "
                f"VA=0x{segment.virtual_address:X} "
                f"FileSize=0x{segment.file_size:X} "
                f"MemSize=0x{segment.memory_size:X} "
                f"{permissions}"
            )

        lines.append("\nセクション：")
        for section in elf_info.sections:
            permissions = "".join(
                permission
                for enabled, permission in (
                    (section.allocatable, "A"),
                    (section.writable, "W"),
                    (section.executable, "X"),
                )
                if enabled
            ) or "-"
            lines.append(
                f"- {section.name or '(名前なし)'} "
                f"Type={section.section_type} "
                f"Address=0x{section.virtual_address:X} "
                f"Offset=0x{section.file_offset:X} "
                f"Size=0x{section.size:X} "
                f"{permissions}"
            )
