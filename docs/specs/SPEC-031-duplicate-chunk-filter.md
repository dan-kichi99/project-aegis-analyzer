# SPEC-031: Local Duplicate Chunk Filtering

## 目的

`KnowledgeRetriever` が返却する上位チャンク内に、同等・酷似した内容のチャンクが複数含まれる問題を軽減する。

これにより、OpenAI APIへ同一内容の重複文章を送信する無駄を削減し、プロンプト内の情報多様性を高めると同時に、API入力トークンコストを節約する。

## 概要

`DuplicateChunkFilter` クラスを新規作成し、Jaccard類似度を用いたローカルかつ軽量な重複判別処理を実装する。
`KnowledgeRetriever` はBM25スコアリング・降順ソート後に本フィルターを適用し、上位3件（`[:3]`）へ切り出す。

## 重複判定仕様 (`DuplicateChunkFilter`)

### クラス定数
- `_SIMILARITY_THRESHOLD = 0.85`

### 依存性 (`TextNormalizer`)
- **Jaccard計算前のトークン化には既存 `TextNormalizer` を利用し、大文字小文字・指定記号による表記揺れ（例: ピリオドの有無、`AES-CBC` と `aes cbc`、`SQL_injection` と `sql injection`）を正規化する。**
- `TextNormalizer` はコンストラクタでDI可能とし、未注入時はデフォルト生成（`self._text_normalizer = text_normalizer or TextNormalizer()`）とする。

### 処理フロー
1. 空白・空文字チャンクを除外する。
2. 各チャンクを `set(self._text_normalizer.normalize(chunk))` により正規化された単語集合（`set[str]`）へ変換する。
3. 2つのチャンク間の Jaccard 類似度を計算する。
   $$\text{Jaccard Similarity} = \frac{\vert{}A \cap B\vert{}}{\vert{}A \cup B\vert{}}$$
4. 類似度が `0.85` 以上の場合、重複と判定する。

### `filter()` 処理詳細
- 採用済みチャンクのリストを保持し、元の入力順序（スコア順）を維持する。
- 1件目の有効チャンクは常に採用する。
- 2件目以降のチャンクについて、採用済みチャンクのいずれかと Jaccard 類似度が `0.85` 以上となった場合は除外する。

## `KnowledgeRetriever` 統合仕様

### コンストラクタ
```python
def __init__(
    self,
    text_chunker: TextChunker | None = None,
    text_normalizer: TextNormalizer | None = None,
    duplicate_chunk_filter: DuplicateChunkFilter | None = None,
    base_dir: Path | str = "data/knowledge",
) -> None:
    self._base_dir = Path(base_dir)
    self._text_chunker = text_chunker or TextChunker()
    self._text_normalizer = text_normalizer or TextNormalizer()
    self._duplicate_chunk_filter = (
        duplicate_chunk_filter
        or DuplicateChunkFilter(text_normalizer=self._text_normalizer)
    )
