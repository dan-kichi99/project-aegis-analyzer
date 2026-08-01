from app.knowledge.knowledge_retriever import KnowledgeRetriever


class RetrieverEvaluator:
    """KnowledgeRetrieverの検索品質（Hit Rate）を評価するクラス。"""

    def __init__(
        self,
        retriever: KnowledgeRetriever,
    ) -> None:
        self._retriever = retriever

    def evaluate(
        self,
        category: str,
        query: str,
        expected_text: str,
    ) -> bool:
        """期待テキストが検索結果に含まれるか判定する。"""
        results = self._retriever.retrieve(category, query)
        expected_lower = expected_text.lower()

        for chunk in results:
            if expected_lower in chunk.lower():
                return True

        return False

    def evaluate_batch(
        self,
        cases: list[tuple[str, str, str]],
    ) -> float:
        """複数ケースのHit Rateを返す。"""
        if not cases:
            return 0.0

        success_count = sum(
            1
            for category, query, expected_text in cases
            if self.evaluate(category, query, expected_text)
        )

        return success_count / len(cases)
