class TextChunker:
    """テキストを一定文字数・オーバーラップ付きで分割するチャンカー"""

    _CHUNK_SIZE: int = 1200
    _OVERLAP: int = 200

    def chunk(self, text: str) -> list[str]:
        """テキストを固定長・オーバーラップ付きで分割する。"""
        stripped_text = text.strip()

        if not stripped_text:
            return []

        if len(stripped_text) <= self._CHUNK_SIZE:
            return [stripped_text]

        chunks: list[str] = []
        step = self._CHUNK_SIZE - self._OVERLAP
        start = 0

        while start < len(stripped_text):
            end = start + self._CHUNK_SIZE
            chunks.append(stripped_text[start:end])

            if end >= len(stripped_text):
                break

            start += step

        return chunks
