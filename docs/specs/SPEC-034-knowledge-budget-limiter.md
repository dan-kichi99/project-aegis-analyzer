# SPEC-034: Knowledge Budget Limiter

## 目的

`KnowledgeRetriever` が返却するプロンプト用ナレッジテキストの合計文字数にローカルの上限を設定する。

これにより、OpenAI API へ送信するプロンプトの入力文字数を抑制し、入力トークン数および API 利用料金を削減するとともに、BM25 スコアが高い上位のチャンクを優先して保持する。

## 概要

`KnowledgeBudgetLimiter` クラスを新規作成し、返却するチャンク群の合計文字数が上限を超えないよう制限する。
`KnowledgeRetriever` 内で重複除去（`DuplicateChunkFilter`）および上位 3 件の切出し（`[:3]`）を行った後に本 limiter を適用する。

## 仕様 (`KnowledgeBudgetLimiter`)

### クラス定数
- `_MAX_TOTAL_CHARS = 3000`

### 処理ルール

1. **入力順の維持**:
   入力された `chunks`（BM25スコア降順・重複除去済み）の並び順を維持したまま、先頭のチャンクから順に採用する。
2. **空チャンク・空白の除外**:
   空文字および空白のみ（`not chunk.strip()`）のチャンクは除外する。
3. **複数チャンクの追加判定**:
   採用済みチャンクの合計文字数に次のチャンクの文字数を加算した値が `3000` 文字を超える場合、そのチャンクは追加せず除外する（途中で部分切り詰めは行わない）。
4. **単一チャンクの超過（truncate ルール）**:
   **最初の 1 件目のチャンク単体ですでに 3000 文字を超えている場合のみ**、先頭 `3000` 文字へスライス（`chunk[:3000]`）して返却する。

## `KnowledgeRetriever` 統合仕様

### コンストラクタ
DI（依存性注入）可能とし、未注入時はデフォルトインスタンスを生成する。

```python
def __init__(
    self,
    text_chunker: TextChunker | None = None,
    text_normalizer: TextNormalizer | None = None,
    duplicate_chunk_filter: DuplicateChunkFilter | None = None,
    knowledge_budget_limiter: KnowledgeBudgetLimiter | None = None,
    base_dir: Path | str = "data/knowledge",
) -> None:
    self._base_dir = Path(base_dir)
    self._text_chunker = text_chunker or TextChunker()
    self._text_normalizer = text_normalizer or TextNormalizer()
    self._duplicate_chunk_filter = (
        duplicate_chunk_filter
        or DuplicateChunkFilter(text_normalizer=self._text_normalizer)
    )
    self._knowledge_budget_limiter = (
        knowledge_budget_limiter or KnowledgeBudgetLimiter()
    )
処理順序（適用タイミング）
全チャンク収集

TextNormalizer によるトークン化

BM25 スコア計算

スコア降順ソート

DuplicateChunkFilter 適用（重複除去）

上位 3 件取得（[:3]）

KnowledgeBudgetLimiter.limit() 適用

最終ナレッジリストを返却

API 料金削減効果
プロンプトに埋め込まれるコンテキストナレッジの総文字数が常に 3,000 文字以内に収まるため、OpenAI API 呼び出し時の入力トークン量の上限が確定し、API 利用料金の削減およびレスポンス速度の向上につながる。

今回実装しないもの（YAGNI）
tiktoken 等による正確なトークン数計測 / モデル別 Token Budget

動的 Budget 調整 / AI による自動要約

2 件目以降のチャンクの途中切り詰め（途中で切らずにまるごと除外する）

Re-ranking / Compression / Embedding / Vector DB

キャッシュ / API 料金直接計算


---

## 2. `app/knowledge/knowledge_budget_limiter.py`

```python
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
                # 最初の1件目のチャンク処理
                if chunk_len > self._MAX_TOTAL_CHARS:
                    # 1件目が上限を超える場合のみ3000文字へ切り詰め
                    limited_chunks.append(chunk[: self._MAX_TOTAL_CHARS])
                    break
                else:
                    limited_chunks.append(chunk)
                    current_total_chars += chunk_len
            else:
                # 2件目以降のチャンク処理（上限を超える場合は途中切り詰めず除外）
                if current_total_chars + chunk_len <= self._MAX_TOTAL_CHARS:
                    limited_chunks.append(chunk)
                    current_total_chars += chunk_len

        return limited_chunks
