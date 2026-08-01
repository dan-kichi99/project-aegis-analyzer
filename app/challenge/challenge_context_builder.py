from app.challenge.challenge_input import ChallengeInput

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

        return "\n".join(lines)
