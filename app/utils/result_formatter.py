from typing import ClassVar

from app.codegen.code_safety_result import CodeRiskLevel
from app.codegen.generated_code_result import (
    GeneratedCodeLanguage,
    GeneratedCodeStatus,
)
from app.judge.judge_result import JudgeResult

_CODE_DISPLAY_LIMIT = 5_000
_RISK_LABELS = {
    CodeRiskLevel.LOW: "低",
    CodeRiskLevel.MEDIUM: "中",
    CodeRiskLevel.HIGH: "高",
    CodeRiskLevel.BLOCKED: "実行禁止",
}


class ResultFormatter:
    """JudgeResultを日本語のCLI表示用文字列へ整形するクラス。"""

    _CATEGORY_LABELS: ClassVar[dict[str, str]] = {
        "Crypto": "暗号",
        "Web": "Web",
        "Rev": "リバース",
        "Misc": "その他",
        "Unknown": "不明",
        "crypto": "暗号",
        "web": "Web",
        "rev": "リバース",
        "misc": "その他",
        "unknown": "不明",
        "general": "一般",
    }

    def format(
        self,
        result: JudgeResult,
    ) -> str:
        """JudgeResultをCLI向けの日本語表示へ変換する。"""
        lines: list[str] = []

        lines.append("Project Aegis 解析結果")
        lines.append("=" * 50)
        lines.append("")

        lines.append("カテゴリ")
        lines.append("=" * 16)

        category = result.category or "general"
        lines.append(
            self._CATEGORY_LABELS.get(
                category,
                category,
            )
        )
        lines.append("")

        lines.append("状態")
        lines.append("=" * 16)
        lines.append(
            "解決済み"
            if result.flag is not None
            else "未解決"
        )
        lines.append("")

        lines.append("信頼度")
        lines.append("=" * 16)

        if isinstance(result.confidence, int):
            lines.append(f"{result.confidence}%")
        else:
            lines.append("不明")

        lines.append("")

        if result.flag:
            lines.append("Flag候補")
            lines.append("=" * 16)
            lines.append(result.flag)
            lines.append("")

        lines.append("AI回答")
        lines.append("=" * 16)
        lines.append(
            result.answer
            or "回答がありません"
        )
        lines.append("")

        answer_text = (
            result.answer or ""
        ).strip()

        reason_text = (
            result.reason or ""
        ).strip()

        if (
            reason_text
            and reason_text != answer_text
        ):
            lines.append("根拠")
            lines.append("=" * 16)
            lines.append(result.reason)
            lines.append("")

        if (
            result.hypothesis
            and result.hypothesis.strip()
        ):
            lines.append("仮説")
            lines.append("=" * 16)
            lines.append(result.hypothesis)
            lines.append("")

        if result.next_actions:
            lines.append("次に試すこと")
            lines.append("=" * 16)

            for action in result.next_actions:
                lines.append(f"- {action}")

            lines.append("")

        if result.generated_code is not None and result.generated_code.items:
            lines.append("生成コード候補")
            lines.append("=" * 16)
            lines.append("")
            for index, item in enumerate(result.generated_code.items, start=1):
                language = (
                    "Python"
                    if item.language is GeneratedCodeLanguage.PYTHON
                    else "不明"
                )
                status = (
                    "要レビュー"
                    if item.status is GeneratedCodeStatus.REVIEW_REQUIRED
                    else "提案"
                )
                lines.append(f"候補 {index}")
                lines.append(f"言語：{language}")
                lines.append(f"状態：{status}")
                if item.purpose:
                    lines.append(f"目的：{item.purpose}")
                lines.append("")
                displayed_code = item.code
                if len(displayed_code) > _CODE_DISPLAY_LIMIT:
                    displayed_code = (
                        displayed_code[:_CODE_DISPLAY_LIMIT] + "\n[表示省略]"
                    )
                lines.append(displayed_code)
                lines.append("")
                if item.safety is not None:
                    lines.append("安全性検査：")
                    lines.append(
                        f"- 総合危険度：{_RISK_LABELS[item.safety.overall_risk]}"
                    )
                    if item.safety.findings:
                        for finding in item.safety.findings:
                            risk = _RISK_LABELS[finding.risk_level]
                            location = (
                                f"{finding.line_number}行目 "
                                if finding.line_number is not None
                                else ""
                            )
                            symbol = f"{finding.symbol} " if finding.symbol else ""
                            lines.append(
                                f"- [{risk}] {location}{symbol}{finding.message}"
                            )
                    else:
                        lines.append("- 検出された危険項目はありません。")
                    lines.append("")
            lines.append("注意：")
            lines.append("静的検査だけではコードの安全性を保証できません。")
            lines.append("現在、このコードは実行できません。")
            lines.append("このコードはまだ実行されていません。")
            lines.append("内容を確認してから実行してください。")
            lines.append("")

        return "\n".join(lines).rstrip()
