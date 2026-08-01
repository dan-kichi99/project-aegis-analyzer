# SPEC-041: Zero-Match Retrieval Guard

## 目的

`KnowledgeRetriever` において、クエリ（および Query Expansion 後の拡張語句）とナレッジベース内のテキストに共通するトークンが1つも存在せず、BM25スコアが全件 0.0 となった場合に、無関係なナレッジ（`raw_chunks` の先頭チャンク）を返却する旧フォールバック挙動を廃止し、正確に空リスト `[]` を返却するガードを導入する。

## 問題となっていた旧挙動

従来は、以下のようにスコアが 0 以下の候補（`sorted_chunks` が空）である場合、データセットの先頭チャンクをそのまま採用するフォールバック処理が存在していた。

```python
# 旧挙動
sorted_chunks = [chunk for score, chunk in scores if score > 0.0]
if not sorted_chunks:
    sorted_chunks = raw_chunks  # <- クエリと無関係なナレッジが返却される要因
この結果、全く無関係なクエリに対してもナレッジが返却され、以下の問題を引き起こしていた。

OpenAI APIのコンテキスト汚染: 無関係なナレッジがシステムプロンプトへ埋め込まれ、LLM が誤った推論（Hallucination / 誤誘導）を起こすリスク。

トークンコストの増大: 不要なテキスト送信による API 利用料金の浪費。

新しい Zero-Match 挙動
BM25 スコア計算後、score > 0.0 となるチャンクが存在しない場合（not sorted_chunks）は、即座に [] を返却する。

Python
# 新挙動
sorted_chunks = [chunk for score, chunk in scores if score > 0.0]
if not sorted_chunks:
    return []
空 Query 処理（既存維持）
入力クエリが空文字 ""、空白のみ "   "、または TextNormalizer による正規化後にトークンが空となった場合は、従来通り [] を返却する。

UNKNOWN カテゴリ処理（既存維持）
Category.UNKNOWN が指定された場合は全カテゴリ（base_dir 全体）を走査する。

ただし、全カテゴリ走査後であっても score > 0.0 のチャンクが存在しない場合は [] を返却する。

処理順序
Target Directory の特定（Category.UNKNOWN の場合は全ディレクトリ）

チャンク収集（raw_chunks が空なら []）

クエリ拡張 (QueryExpander.expand) ＆ 正規化 (TextNormalizer.normalize)

正規化後クエリトークン検証（空なら []）

BM25 スコアリング計算

Zero-Match Guard: score > 0.0 のチャンク抽出（存在しなければ [] を返却）

重複フィルタリング (DuplicateChunkFilter.filter)

スライス制限 ([:3])

予算制限 (KnowledgeBudgetLimiter.limit)

API 料金削減効果
無関係なクエリに対して不要なコンテキスト（最大 3 チャンク / 指定文字数上限まで）が LLM プロンプトに挿入されることを防ぐため、入力トークン数を削減し、従量課金API（OpenAI API等）のコスト効率を高める。また、PromptManager の既存仕様（No local knowledge available.）と連携し、不要な処理を最小化する。

今回実装しないもの（YAGNI）
スコア閾値（Score threshold）のカスタマイズ

最低 BM25 スコア値の設定

Vector DB / Embedding / Semantic Search 導入

AI によるナレッジ関連性判定

Re-ranking / 降順スコアに基づく動的再評価

Query Expansion 辞書の追加・変更

Fallback Web 検索 / 再検索ロジック

検索ログ出力 / メトリクス収集


---

### 2. `app/knowledge/knowledge_retriever.py`（修正）

```python
import math
from pathlib import Path

from app.analyzer.analyzer import Category
from app.knowledge.duplicate_chunk_filter import DuplicateChunkFilter
from app.knowledge.knowledge_budget_limiter import KnowledgeBudgetLimiter
from app.knowledge.query_expander import QueryExpander
from app.knowledge.text_chunker import TextChunker
from app.knowledge.text_normalizer import TextNormalizer


class KnowledgeRetriever:
    """カテゴリ別ナレッジ検索クラス (BM25 + QueryExpansion + BudgetLimiter)"""

    _CATEGORY_DIR_MAP = {
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
    ) -> None:
        self._base_dir = Path(base_dir)
        self._chunker = chunker or TextChunker()
        self._normalizer = normalizer or TextNormalizer()
        self._dedup_filter = dedup_filter or DuplicateChunkFilter()
        self._budget_limiter = budget_limiter or KnowledgeBudgetLimiter()
        self._query_expander = query_expander or QueryExpander()

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

        # 1. チャンク収集
        raw_chunks: list[str] = []
        for file_path in target_dir.rglob("*.txt"):
            try:
                content = file_path.read_text(encoding="utf-8")
                raw_chunks.extend(self._chunker.chunk(content))
            except (UnicodeDecodeError, OSError):
                continue

        if not raw_chunks:
            return []

        # 2. クエリ拡張 & 正規化
        expanded_query = self._query_expander.expand(query)
        query_terms = self._normalizer.normalize(expanded_query)

        if not query_terms:
            return []

        # 3. 各チャンクの正規化 & ドキュメント統計
        doc_tokens_list: list[list[str]] = [
            self._normalizer.normalize(c) for c in raw_chunks
        ]
        N = len(raw_chunks)
        if N == 0:
            return []

        avgdl = sum(len(d) for d in doc_tokens_list) / N

        # 4. BM25 スコアリング
        k1 = 1.5
        b = 0.75
        scores: list[tuple[float, str]] = []

        for idx, (chunk, doc_terms) in enumerate(zip(raw_chunks, doc_tokens_list)):
            doc_len = len(doc_terms)
            score = 0.0
            if doc_len == 0:
                scores.append((0.0, chunk))
                continue

            for q_term in query_terms:
                tf = doc_terms.count(q_term)
                if tf == 0:
                    continue
                df = sum(1 for d in doc_tokens_list if q_term in d)
                idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)
                num = tf * (k1 + 1.0)
                den = tf + k1 * (1.0 - b + b * (doc_len / (avgdl if avgdl > 0 else 1.0)))
                score += idf * (num / den)

            scores.append((score, chunk))

        # スコア降順ソート
        scores.sort(key=lambda x: x[0], reverse=True)

        # 5. Zero-Match Guard (score > 0.0 のチャンクが存在しなければ [] を返却)
        sorted_chunks = [chunk for score, chunk in scores if score > 0.0]
        if not sorted_chunks:
            return []

        deduplicated_chunks = self._dedup_filter.filter(sorted_chunks)
        top_candidates = deduplicated_chunks[:3]

        return self._budget_limiter.limit(top_candidates)
