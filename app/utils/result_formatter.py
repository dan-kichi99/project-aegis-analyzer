from typing import ClassVar

from app.codegen.code_safety_result import CodeRiskLevel
from app.codegen.generated_code_result import (
    GeneratedCodeLanguage,
    GeneratedCodeStatus,
)
from app.execution.execution_analysis_result import (
    ExecutionAnalysisResult,
    ExecutionOutputSource,
)
from app.execution.execution_result import ExecutionStatus, PythonExecutionResult
from app.judge.judge_result import JudgeResult

_CODE_DISPLAY_LIMIT = 5_000
_RISK_LABELS = {
    CodeRiskLevel.LOW: "低",
    CodeRiskLevel.MEDIUM: "中",
    CodeRiskLevel.HIGH: "高",
    CodeRiskLevel.BLOCKED: "実行禁止",
}
_STATUS_LABELS = {
    GeneratedCodeStatus.PROPOSED: "提案",
    GeneratedCodeStatus.REVIEW_REQUIRED: "要レビュー",
    GeneratedCodeStatus.APPROVED: "承認済み・未実行",
    GeneratedCodeStatus.REJECTED: "拒否済み",
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
                status = _STATUS_LABELS[item.status]
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
            if any(
                item.status is GeneratedCodeStatus.APPROVED
                for item in result.generated_code.items
            ):
                lines.append("承認済みですが、コードはまだ実行されていません。")
            lines.append("このコードはまだ実行されていません。")
            lines.append("内容を確認してから実行してください。")
            lines.append("")

        return "\n".join(lines).rstrip()

    def format_execution(self, result: PythonExecutionResult) -> str:
        """制限付きコード実行の結果を安全上の注意とともに表示する。"""
        status_labels = {
            ExecutionStatus.COMPLETED: "完了",
            ExecutionStatus.TIMED_OUT: "タイムアウト",
            ExecutionStatus.REJECTED: "拒否",
            ExecutionStatus.FAILED: "失敗",
        }
        exit_code = "不明" if result.exit_code is None else str(result.exit_code)
        lines = [
            "コード実行結果",
            "=" * 16,
            f"状態：{status_labels[result.status]}",
            f"終了コード：{exit_code}",
            f"実行時間：{result.duration_seconds:.2f}秒",
            "",
            "標準出力：",
            result.stdout or "なし",
            "",
            "標準エラー：",
            result.stderr or "なし",
        ]
        if result.output_truncated:
            lines.extend(("", "出力は上限を超えたため省略されています。"))
        lines.extend(
            (
                "",
                "注意：",
                "この処理は制限付き実行であり、完全なサンドボックスではありません。",
                "出力中のFlagらしい文字列はまだ正解判定されていません。",
            )
        )
        return "\n".join(lines)

    def format_execution_analysis(
        self,
        result: ExecutionAnalysisResult,
    ) -> str:
        """実行出力のFlag候補を正解と断定せず表示する。"""
        lines = [
            "実行結果解析",
            "=" * 16,
            f"実行成功：{'はい' if result.successful_execution else 'いいえ'}",
            f"Flag候補数：{len(result.flag_candidates)}",
            f"主要候補：{result.primary_flag or 'なし'}",
            "",
        ]
        if result.flag_candidates:
            lines.append("実行出力からFlag候補を検出しました。")
            lines.append("正解とは限らないため、問題内容と照合してください。")
            lines.append("")
            lines.append("Flag候補：")
            for candidate in result.flag_candidates:
                source = (
                    "標準出力"
                    if candidate.source is ExecutionOutputSource.STDOUT
                    else "標準エラー"
                )
                lines.append(f"- {candidate.flag}")
                lines.append(f"  検出元：{source}")
        else:
            lines.append("実行出力からFlag候補は検出されませんでした。")
        if not result.successful_execution and result.execution.started:
            lines.extend(
                (
                    "",
                    "実行は正常終了していません。",
                    "表示されたFlag候補は途中出力の可能性があります。",
                )
            )
        if result.execution.output_truncated:
            lines.extend(
                (
                    "",
                    "出力が省略されているため、",
                    "未表示部分に別のFlag候補が存在する可能性があります。",
                )
            )
        lines.extend(
            (
                "",
                "注意：",
                "実行出力に含まれるFlag形式の文字列を候補として表示しています。",
                "正解Flagであることは保証されません。",
            )
        )
        return "\n".join(lines)
