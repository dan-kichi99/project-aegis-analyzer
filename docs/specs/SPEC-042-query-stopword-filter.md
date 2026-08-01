# SPEC-042: Query Stopword Filter (Low-Signal Query Guard)

## 目的

`KnowledgeRetriever` において、`"the"`, `"this"`, `"using"`, `"challenge"` などの一般的かつ情報量の低い単語（Low-Signal Words）のみがナレッジ文書と部分一致した場合に、BM25 スコアが 0 より大きくなり意図しない無関係なナレッジが返却されるリスクを防止する。

外部ライブラリ（NLTK, spaCy 等）や外部 API に依存せず、小規模な固定 Stop Word セットを用いて**検索クエリ側のみ**フィルタリングを行う。

## Low-Signal 問題と背景

従来の BM25 検索では、以下のようなクエリが入力された場合に不要な検索結果が返る懸念があった。
- クエリ: `"the challenge using this problem"`
- `TextNormalizer` 後のトークン: `["the", "challenge", "using", "this", "problem"]`
- ナレッジ本文中に `"the"` や `"challenge"` が含まれる場合、BM25 スコアが正（$>0.0$）となり `Zero-Match Guard` (TASK-041) をすり抜けて上位候補として返却される。

## Stop Word 設定

以下に示す 33 個の小規模固定セットを使用する。

```python
_STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "is", "are", "was", "were",
    "be", "been", "being", "to", "of", "in", "on", "for", "with",
    "from", "by", "as", "at", "this", "that", "these", "those", "it",
    "its", "using", "use", "challenge", "problem",
}
注意 (CTFドメイン知識の保護):web, rsa, jwt, json, token, ghidra, reverse, engineering, xor, encryption, sql, aes などの CTF / セキュリティ関連で意味を持つ重要な用語は絶対に含まない。Query 側だけに適用する理由IDF（逆文書頻度）計算への悪影響防止: BM25 の IDF 計算（$N$ や $df$ の統計値）およびドキュメント長（$doc\_len$, $avgdl$）の整合性を保つため、ナレッジ本文側（doc_tokens_list）のトークン構成は変更しない。計算コスト抑制: ナレッジ本文のトークンフィルタリングを回避し、クエリ側のトークン配列（数個〜十数個）のみを判定することで処理速度を維持する。適用タイミングと処理順序KnowledgeRetriever.retrieve() 内の処理順序は以下の通り。チャンク収集 (raw_chunks)クエリ拡張 (QueryExpander.expand)クエリ正規化 (TextNormalizer.normalize)Query Stopword Filtering (QueryStopwordFilter.filter) $\leftarrow$ 新規挿入トークン存在検証（if not query_terms: return []）BM25 スコアリング計算Zero-Match Guard (if not sorted_chunks: return [])重複除外 (DuplicateChunkFilter.filter)スライス制限 ([:3])予算制限 (KnowledgeBudgetLimiter.limit)空 Query 処理・Stop Word のみ Query 処理クエリが最初から空（"", "   "）の場合や、QueryStopwordFilter 適用後にすべてのトークンが除去されて query_terms が空リスト [] になった場合（例: クエリが "the and this problem using" のみ）、即座に空リスト [] を返却する。API 料金削減効果Stop Word のみで構成された検索（実質的に無意味な検索）や Stop Word の一致のみによる誤検索を入口段階で早期遮断することにより、不要なナレッジが LLM プロンプトに埋め込まれる事態を完全に回避する。これにより、OpenAI API への入力トークン消費を抑え、従量課金コストを低減する。今回実装しないもの（YAGNI）大規模 Stop Word 辞書（NLTK Stopwords 等）NLP ライブラリ導入（NLTK, spaCy, MeCab, Sudachi 等）Stemming / Lemmatization (ステミング / 語形変化正規化)自動 Stop Word 抽出 / TF-IDF による動的フィルタリングBM25 スコア計算式の変更 / 閾値設定ナレッジ本文側の Stop Word 除外
---

### 2. `app/knowledge/query_stopword_filter.py`（新規作成）

```python
class QueryStopwordFilter:
    """検索クエリのトークンリストから小規模な英語 Stop Word を除外するクラス。"""

    _STOP_WORDS: set[str] = {
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
        """トークンリストを入力順序を維持したまま Stop Word を除外して返却する。"""
        if not tokens:
            return []

        return [token for token in tokens if token not in self._STOP_WORDS]
