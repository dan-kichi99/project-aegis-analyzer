class GeminiPromptGenerator:
    """Geminiへ渡すためのプロンプトを生成するクラス（現段階では固定テンプレート基盤のみ）"""

    def generate(
        self,
        category: str,
        response: str,
    ) -> str:
        """
        カテゴリおよび応答文を受け取り、Gemini向けプロンプトを生成して返却する。
        """
        return f"""This is a Capture The Flag (CTF) challenge for educational and competition purposes.

Category:
{category}

Previous analysis:
{response}

Generate the code or technical steps needed to continue solving the challenge.
Keep the output focused on the supplied CTF challenge."""
