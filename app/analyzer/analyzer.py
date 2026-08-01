class Category:
    CRYPTO = "Crypto"
    WEB = "Web"
    REV = "Rev"
    MISC = "Misc"
    UNKNOWN = "Unknown"


class Analyzer:
    """入力テキストから問題カテゴリを判定するクラス"""

    _CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            Category.CRYPTO,
            (
                "rsa",
                "aes",
                "cipher",
                "key",
                "hash",
                "ecc",
                "crt",
                "xor",
                "base64",
                "rot13",
                "vigenere",
                "cbc",
                "ecb",
                "padding",
            ),
        ),
        (
            Category.WEB,
            (
                "http",
                "https",
                "url",
                "sql",
                "xss",
                "cookie",
                "jwt",
                "php",
                "req",
                "flask",
                "session",
                "csrf",
                "ssti",
                "lfi",
                "rfi",
                "upload",
                "login",
            ),
        ),
        (
            Category.REV,
            (
                "binary",
                "elf",
                "gdb",
                "disassemble",
                "assembly",
                "reverse",
                "ida",
                "ghidra",
                "exe",
                "dll",
                "strings",
                "objdump",
            ),
        ),
        (
            Category.MISC,
            (
                "osint",
                "discord",
                "nc",
                "stego",
                "zip",
                "forensics",
                "pcap",
                "image",
                "png",
                "jpg",
                "pdf",
                "audio",
                "wav",
            ),
        ),
    )

    def analyze(self, text: str) -> str:
        """
        入力テキストを解析し、優先順位に基づいて最初に合致したカテゴリ文字列を返却する。
        該当するキーワードがない場合は Category.UNKNOWN を返却する。
        """
        text_lower = text.lower().strip()

        for category, keywords in self._CATEGORY_RULES:
            if any(keyword in text_lower for keyword in keywords):
                return category

        return Category.UNKNOWN
