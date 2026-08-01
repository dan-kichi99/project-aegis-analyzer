# SPEC-040: Local Query Expansion Dictionary

## 目的

TASK-039（Hard Retrieval Benchmark）で観測された「語彙ミスマッチ」（例: クエリ中の "close prime factors" とナレッジ本文中の "Fermat" 等の不一致）による検索失敗を改善するため、外部 API や Embedding / Vector DB を使用しない完全ローカルの軽量 Query Expansion（クエリ拡張）辞書を導入する。

検索方式（BM25）やスコア計算式、ノーマライザは変更せず、検索クエリにトリガー語句に基づく補足キーワードを動的に追加することで再現率（Recall）と精度を向上させる。

## 構造と仕様

### `QueryExpander` (`app/knowledge/query_expander.py`)

#### クラス定義
```python
class QueryExpander:
    def __init__(self) -> None:
        ...

    def expand(self, query: str) -> str:
        ...
規則テーブル (_EXPANSION_RULES)トリガーフレーズ（タプル）と、付与する拡張テキスト（タプル）のペアを保持する。主な適用領域:Fermat Factorization: "close prime", "prime factors are close", "factors are near", "same size primes", "factors are almost the same size" 等 $\rightarrow$ "fermat factorization"JWT (JSON Web Token): "unsigned token", "algorithm none", "token signature", "alg none" 等 $\rightarrow$ "jwt json web token"Ghidra: "decompiler", "c pseudocode", "cross references", "xrefs" 等 $\rightarrow$ "ghidra reverse engineering"XOR Encryption: "bitwise operation", "constant byte", "self inverse", "bitwise xor" 等 $\rightarrow$ "xor encryption"expand(query: str) -> str 処理フロー入力 query が空文字または空白のみの場合、"" または元の文字列を返却する。query を小文字化 (query.lower()) してトリガー判定に使用（元の query は保持）。定義ルールを順次評価し、いずれかのトリガーフレーズが小文字化クエリに含まれる場合、拡張テキストを追加リストへ追加。重複排除: 同一の拡張テキストが複数ルールにより二重に追加されないよう制御する。元の query の末尾に、適用された拡張テキストをスペース区切りで結合して返却する。KnowledgeRetriever 統合 (app/knowledge/knowledge_retriever.py)コンストラクタ拡張Pythondef __init__(
    self,
    base_dir: str | Path = "data/knowledge",
    chunker: TextChunker | None = None,
    normalizer: TextNormalizer | None = None,
    dedup_filter: DuplicateChunkFilter | None = None,
    budget_limiter: KnowledgeBudgetLimiter | None = None,
    query_expander: QueryExpander | None = None,
) -> None:
query_expander が未注入（None）の場合は、デフォルトで QueryExpander() のインスタンスを自動生成・使用する。retrieve() 実行順序元の query を受領expanded_query = self._query_expander.expand(query)query_terms = self._normalizer.normalize(expanded_query)query_terms が空の場合は [] を返却BM25 スコア計算 $\rightarrow$ スコア降順ソートscore > 0 の全候補抽出（なければ raw_chunks フォールバック）DuplicateChunkFilter 適用Top3 スライス ([:3])KnowledgeBudgetLimiter 適用今回実装しないもの（YAGNI）Embedding / Vector DB (FAISS, Chroma)Semantic Search / AI Query Expansion (LLM 呼び出し)WordNet / 外部大容量辞書形態素解析器 (MeCab, Sudachi) / Stemming / LemmatizationRe-ranking / 自動辞書学習Web 検索 / データベース保存
---

## 2. `app/knowledge/query_expander.py`（新規作成）

```python
class QueryExpander:
    """ローカルルールに基づき、検索クエリに拡張キーワードを付与するクラス。"""

    _EXPANSION_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
        # 1. Fermat Factorization
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
        # 2. JWT
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
        # 3. Ghidra
        (
            (
                "decompiler",
                "c pseudocode",
                "cross references",
                "xrefs",
            ),
            ("ghidra", "reverse", "engineering"),
        ),
        # 4. XOR
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
        """入力クエリを評価し、トリガー句にマッチした場合に拡張語句を末尾へ追加する。"""
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
