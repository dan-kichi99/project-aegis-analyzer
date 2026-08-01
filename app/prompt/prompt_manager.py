from typing import ClassVar

from app.analyzer.analyzer import Category


class PromptManager:
    """カテゴリに応じたテンプレートを用いてAI用プロンプトを構築するクラス"""

    _TEMPLATES: ClassVar[dict[str, str]] = {
        Category.CRYPTO: (
            "You are an expert in Cryptography and CTF challenges.\n"
            "Analyze the given question, identify the encryption scheme or vulnerability, "
            "and provide step-by-step instructions or Python scripts to decrypt the ciphertext or recover the key.\n\n"
            "Question:\n{question}"
        ),
        Category.WEB: (
            "You are an expert in Web Security and CTF challenges.\n"
            "Analyze the given question, identify the web vulnerability (e.g., SQLi, XSS, CSRF, SSTI), "
            "and provide payloads or exploitation steps to retrieve the flag.\n\n"
            "Question:\n{question}"
        ),
        Category.REV: (
            "You are an expert in Reverse Engineering and CTF challenges.\n"
            "Analyze the given question, disassemble/decompile instructions, "
            "and provide reverse engineering methodology or script to extract the flag.\n\n"
            "Question:\n{question}"
        ),
        Category.MISC: (
            "You are an expert in Miscellaneous CTF challenges (Forensics, OSINT, Steganography, etc.).\n"
            "Analyze the given question and provide concrete steps or tools to uncover the flag.\n\n"
            "Question:\n{question}"
        ),
        Category.UNKNOWN: (
            "You are an expert in Cybersecurity and CTF challenges.\n"
            "Analyze the given general security problem and provide detailed guidance and solutions.\n\n"
            "Question:\n{question}"
        ),
    }

    def build(
        self,
        question: str,
        category: str,
        knowledge: list[str],
    ) -> str:
        """
        質問テキスト、カテゴリ判定結果、ナレッジリストを基に最適化されたプロンプトを構築する。
        """
        template = self._TEMPLATES.get(
            category,
            self._TEMPLATES[Category.UNKNOWN],
        )
        base_prompt = template.format(question=question)

        if knowledge:
            knowledge_text = "\n\n---\n\n".join(knowledge)
        else:
            knowledge_text = "No local knowledge available."

        return (
            f"{base_prompt}\n\n"
            f"Relevant local knowledge:\n"
            f"{knowledge_text}"
        )