from typing import ClassVar

from app.judge.judge_result import JudgeResult


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

        return "\n".join(lines).rstrip()