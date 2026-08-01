class TextNormalizer:
    """ローカル検索向けの軽量テキスト正規化クラス。"""

    # 置換対象の記号定義
    _PUNCTUATION_TARGETS = (
        ",",
        ".",
        ":",
        ";",
        "(",
        ")",
        "[",
        "]",
        "{",
        "}",
        '"',
        "'",
        "/",
        "\\",
        "|",
        "-",
        "_",
        "=",
        "+",
        "*",
        "!",
        "?",
        "#",
        "@",
    )

    def normalize(self, text: str) -> list[str]:
        """テキストを小文字化し、記号を空白に置換してトークンリストを返却する。"""
        if not text:
            return []

        lowered = text.lower()
        for char in self._PUNCTUATION_TARGETS:
            lowered = lowered.replace(char, " ")

        return lowered.split()
