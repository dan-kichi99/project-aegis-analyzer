

class ConfidenceEstimator:
    """AI回答の信頼度をルールベースで推定するクラス"""

    UNCERTAIN_WORDS: tuple[str, ...] = (
        "maybe",
        "possibly",
        "might",
        "not sure",
        "uncertain",
        "probably",
    )

    def estimate(
        self,
        category: str,
        response: str,
        flag: str | None,
    ) -> int:
        """
        カテゴリ、AIの応答、および抽出されたフラグを受け取り、ルールベースで信頼度(0~100)を推定して返却する。
        """
        score = 50

        if flag is not None:
            score += 30

        response_lower = response.lower()
        if any(word in response_lower for word in self.UNCERTAIN_WORDS):
            score -= 20

        return max(0, min(100, score))
