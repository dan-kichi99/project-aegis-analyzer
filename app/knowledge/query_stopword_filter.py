from typing import ClassVar


class QueryStopwordFilter:
    """検索クエリのトークンリストから小規模な英語Stop Wordを除外するクラス。"""

    _STOP_WORDS: ClassVar[set[str]] = {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "to",
        "of",
        "in",
        "on",
        "for",
        "with",
        "from",
        "by",
        "as",
        "at",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "using",
        "use",
        "challenge",
        "problem",
    }

    def filter(self, tokens: list[str]) -> list[str]:
        """入力順序を維持したままStop Wordを除外する。"""
        if not tokens:
            return []

        return [
            token
            for token in tokens
            if token not in self._STOP_WORDS
        ]