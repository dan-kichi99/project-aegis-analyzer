import math
from pathlib import Path
from typing import ClassVar

from app.analyzer.analyzer import Category
from app.knowledge.duplicate_chunk_filter import DuplicateChunkFilter
from app.knowledge.knowledge_budget_limiter import KnowledgeBudgetLimiter
from app.knowledge.query_expander import QueryExpander
from app.knowledge.query_stopword_filter import QueryStopwordFilter
from app.knowledge.text_chunker import TextChunker
from app.knowledge.text_normalizer import TextNormalizer


class KnowledgeRetriever:
    """カテゴリ別ナレッジ検索クラス (BM25 + QueryExpansion + StopwordFilter + BudgetLimiter)"""

    _CATEGORY_DIR_MAP: ClassVar[dict[str, str]] = {
        Category.CRYPTO: "crypto",
        Category.WEB: "web",
        Category.REV: "rev",
        Category.MISC: "misc",
    }

    def __init__(
        self,
        base_dir: str | Path = "data/knowledge",
        chunker: TextChunker | None = None,
        normalizer: TextNormalizer | None = None,
        dedup_filter: DuplicateChunkFilter | None = None,
        budget_limiter: KnowledgeBudgetLimiter | None = None,
        query_expander: QueryExpander | None = None,
        query_stopword_filter: QueryStopwordFilter | None = None,
    ) -> None:
        self._base_dir = Path(base_dir)
        self._chunker = chunker or TextChunker()
        self._normalizer = normalizer or TextNormalizer()
        self._dedup_filter = dedup_filter or DuplicateChunkFilter()
        self._budget_limiter = budget_limiter or KnowledgeBudgetLimiter()
        self._query_expander = query_expander or QueryExpander()
        self._query_stopword_filter = (
            query_stopword_filter or QueryStopwordFilter()
        )

    def _get_target_dir(self, category: str) -> Path | None:
        if category == Category.UNKNOWN:
            return self._base_dir

        dir_name = self._CATEGORY_DIR_MAP.get(category)

        if dir_name is None:
            return None

        return self._base_dir / dir_name

    def retrieve(self, category: str, query: str) -> list[str]:
        target_dir = self._get_target_dir(category)

        if target_dir is None or not target_dir.exists():
            return []

        raw_chunks: list[str] = []

        for file_path in target_dir.rglob("*.txt"):
            try:
                content = file_path.read_text(encoding="utf-8")
                raw_chunks.extend(self._chunker.chunk(content))
            except (UnicodeDecodeError, OSError):
                continue

        if not raw_chunks:
            return []

        expanded_query = self._query_expander.expand(query)
        query_terms = self._normalizer.normalize(expanded_query)
        query_terms = self._query_stopword_filter.filter(query_terms)

        if not query_terms:
            return []

        doc_tokens_list: list[list[str]] = [
            self._normalizer.normalize(chunk)
            for chunk in raw_chunks
        ]

        n_docs = len(raw_chunks)

        if n_docs == 0:
            return []

        avgdl = (
            sum(len(tokens) for tokens in doc_tokens_list)
            / n_docs
        )

        k1 = 1.5
        b = 0.75

        scores: list[tuple[float, str]] = []

        for chunk, doc_terms in zip(
            raw_chunks,
            doc_tokens_list,
        ):
            doc_len = len(doc_terms)
            score = 0.0

            if doc_len == 0:
                scores.append((0.0, chunk))
                continue

            for query_term in query_terms:
                tf = doc_terms.count(query_term)

                if tf == 0:
                    continue

                df = sum(
                    1
                    for tokens in doc_tokens_list
                    if query_term in tokens
                )

                idf = math.log(
                    (
                        n_docs - df + 0.5
                    )
                    / (
                        df + 0.5
                    )
                    + 1.0
                )

                numerator = tf * (k1 + 1.0)

                denominator = (
                    tf
                    + k1
                    * (
                        1.0
                        - b
                        + b
                        * (
                            doc_len
                            / (
                                avgdl
                                if avgdl > 0
                                else 1.0
                            )
                        )
                    )
                )

                score += (
                    idf
                    * (
                        numerator
                        / denominator
                    )
                )

            scores.append((score, chunk))

        scores.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        sorted_chunks = [
            chunk
            for score, chunk in scores
            if score > 0.0
        ]

        if not sorted_chunks:
            return []

        deduplicated_chunks = self._dedup_filter.filter(
            sorted_chunks
        )

        top_candidates = deduplicated_chunks[:3]

        return self._budget_limiter.limit(
            top_candidates
        )