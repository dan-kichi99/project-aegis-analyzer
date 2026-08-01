class KnowledgeBudgetLimiter:
    """検索結果チャンクの合計文字数を指定上限内に制限するクラス。"""

    _MAX_TOTAL_CHARS = 3000

    def limit(self, chunks: list[str]) -> list[str]:
        """チャンクの合計文字数が上限を超えないよう制限して返却する。"""
        if not chunks:
            return []

        limited_chunks: list[str] = []
        current_total_chars = 0

        for chunk in chunks:
            if not chunk or not chunk.strip():
                continue

            chunk_len = len(chunk)

            if not limited_chunks:
                if chunk_len > self._MAX_TOTAL_CHARS:
                    limited_chunks.append(
                        chunk[: self._MAX_TOTAL_CHARS]
                    )
                    break

                limited_chunks.append(chunk)
                current_total_chars += chunk_len
                continue

            if current_total_chars + chunk_len <= self._MAX_TOTAL_CHARS:
                limited_chunks.append(chunk)
                current_total_chars += chunk_len

        return limited_chunks
