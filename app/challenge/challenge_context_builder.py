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
            "Challenge Question:",
            question,
            "",
            "Attached Files:",
        ]

        if not challenge.files:
            lines.append("None")
            return "\n".join(lines)

        for index, file_res in enumerate(challenge.files, start=1):
            lines.append(f"\n[File {index}]")
            lines.append(f"Name: {file_res.name}")
            lines.append(f"Detected Type: {file_res.detected_type}")
            lines.append(f"Size: {file_res.size} bytes")
            lines.append(f"Extension: {file_res.extension}")

            lines.append("\nText Content:")
            if file_res.text_content is None:
                lines.append("Not available")
            else:
                text = file_res.text_content
                if len(text) > _TEXT_CONTENT_LIMIT:
                    text = text[:_TEXT_CONTENT_LIMIT] + "\n[truncated]"
                lines.append(text)

            lines.append("\nExtracted Strings:")
            if not file_res.strings:
                lines.append("None")
            else:
                limited_strings = file_res.strings[:_STRINGS_CONTEXT_LIMIT]
                for s in limited_strings:
                    lines.append(f"- {s}")

        return "\n".join(lines)
