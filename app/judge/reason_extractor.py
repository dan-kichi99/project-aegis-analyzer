class ReasonExtractor:
    """AI回答から理由・解説(reason)を抽出するクラス（現段階では基盤実装のみ）"""

    def extract(
        self,
        response: str,
    ) -> str:
        """
        AIの応答を受け取り、解説テキストを返却する。
        現段階では加工を行わず、responseをそのまま返却する。
        """
        return response
