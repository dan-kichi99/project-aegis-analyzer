class QueryExpander:
    """ローカルルールに基づき、検索クエリに拡張キーワードを付与するクラス。"""

    _EXPANSION_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
        (
            (
                "close prime",
                "prime factors are close",
                "factors are near",
                "same size primes",
                "factors are almost the same size",
                "very near each other",
            ),
            ("fermat", "factorization"),
        ),
        (
            (
                "unsigned token",
                "algorithm none",
                "algorithm set to none",
                "token signature",
                "alg none",
            ),
            ("jwt", "json", "web", "token"),
        ),
        (
            (
                "decompiler",
                "c pseudocode",
                "cross references",
                "xrefs",
            ),
            ("ghidra", "reverse", "engineering"),
        ),
        (
            (
                "bitwise operation",
                "constant byte",
                "self inverse",
                "bitwise xor",
            ),
            ("xor", "encryption"),
        ),
    )

    def expand(self, query: str) -> str:
        """入力クエリを評価し、マッチした関連語を末尾へ追加する。"""
        if not query or not query.strip():
            return query

        query_lower = query.lower()
        added_words: list[str] = []

        for triggers, expansions in self._EXPANSION_RULES:
            if any(trigger in query_lower for trigger in triggers):
                for word in expansions:
                    if word not in added_words and word not in query_lower:
                        added_words.append(word)

        if not added_words:
            return query

        return f"{query} {' '.join(added_words)}"
