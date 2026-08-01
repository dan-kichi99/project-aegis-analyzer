from app.knowledge.text_normalizer import TextNormalizer


class DuplicateChunkFilter:
    """Jaccard類似度を用いて重複チャンクを除外するクラス。"""

    _SIMILARITY_THRESHOLD = 0.85

    def __init__(
        self,
        text_normalizer: TextNormalizer | None = None,
    ) -> None:
        self._text_normalizer = text_normalizer or TextNormalizer()

    def filter(self, chunks: list[str]) -> list[str]:
        """類似度の高い重複チャンクを除外し、入力順を維持して返却する。"""
        if not chunks:
            return []

        filtered_chunks: list[str] = []
        filtered_sets: list[set[str]] = []

        for chunk in chunks:
            if not chunk or not chunk.strip():
                continue

            current_set = set(self._text_normalizer.normalize(chunk))

            if not current_set:
                continue

            is_duplicate = False

            for previous_set in filtered_sets:
                intersection = len(current_set & previous_set)
                union = len(current_set | previous_set)

                if union == 0:
                    continue

                similarity = intersection / union

                if similarity >= self._SIMILARITY_THRESHOLD:
                    is_duplicate = True
                    break

            if not is_duplicate:
                filtered_chunks.append(chunk)
                filtered_sets.append(current_set)

        return filtered_chunks
