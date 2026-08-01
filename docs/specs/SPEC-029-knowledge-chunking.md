# SPEC-029: Knowledge Chunking for Local Retrieval

## 目的

`KnowledgeRetriever` において、`.txt` ファイル全文を1文書として扱う方式を改善し、長文テキストをローカルで指定サイズのチャンクへ分割してから BM25 検索を行えるようにする。

これにより、関連箇所の検索精度向上と AI モデルへ送信するトークン量（不要テキスト）の削減を実現する。

## 概要

`TextChunker` クラスを新規作成し、文字数ベースの固定長・オーバーラップ付きでテキストを分割する。

`KnowledgeRetriever` は読み込んだテキストを `TextChunker` でチャンク化し、各チャンクを独立した文書（Document）として BM25 スコアリングを行う。

## チャンク仕様 (`TextChunker`)

### 定数パラメータ

- `_CHUNK_SIZE = 1200`: チャンクあたりの最大文字数
- `_OVERLAP = 200`: 隣接するチャンク間で重複させる文字数

### 分割アルゴリズム

1. 入力テキスト全体を `.strip()` する。
2. 入力が空文字列の場合は空リスト `[]` を返却する。
3. 文字数が 1200 文字以下の場合は `[text]` を返却する。
4. 1200 文字を超える場合は、開始インデックス `start` を `0` から起算し、`start` から `start + 1200` の範囲を切り出す。
5. 次のチャンクの開始位置を `start += (1200 - 200)` とし、実質 `step = 1000` で順次切り出す。
6. 最終チャンクが 1200 文字未満の場合でも、そのまま返却対象とする。

## KnowledgeRetriever コンストラクタ

```python
def __init__(
    self,
    text_chunker: TextChunker | None = None,
    base_dir: Path | str = "data/knowledge",
) -> None:
    self._base_dir = Path(base_dir)
    self._text_chunker = text_chunker or TextChunker()
