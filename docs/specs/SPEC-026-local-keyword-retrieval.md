# SPEC-026: Local Keyword Knowledge Retrieval

## 目的

`KnowledgeRetriever` へ、ローカルテキストファイル（`data/knowledge/`）を対象とした無料のキーワード検索機能を追加する。

## 概要

外部APIやVector DB、Embeddingを使用せず、`data/knowledge/` 配下のカテゴリ別フォルダ内にある `.txt` ファイルを対象に、クエリ単語の出現頻度に基づくローカルキーワード検索を行う。

## 検索対象ディレクトリ

`data/knowledge/`

- `data/knowledge/crypto/` (`Category.CRYPTO`)
- `data/knowledge/web/` (`Category.WEB`)
- `data/knowledge/rev/` (`Category.REV`)
- `data/knowledge/misc/` (`Category.MISC`)
- `Category.UNKNOWN` または未定義カテゴリの場合は `data/knowledge/` 配下全体を対象とする

## 検索対象ファイル

- `.txt` ファイルのみ（`.md`, `.pdf`, `.html`, `.json` 等は対象外）

## 検索ルール・アルゴリズム

1. `query` を小文字化し、空白で単語リスト（キーワード）へ分割
2. 対象カテゴリフォルダ（または全体）から `.txt` ファイルを探索
3. `UTF-8` でファイルを読み込み、テキストを小文字化
4. 分割した各キーワードが本文中に含まれる総回数をスコアとする
5. スコアが `0` の文書は除外
6. スコアの降順でソート
7. 上位最大3件の本文テキスト（`list[str]`）を返却

## 今回実装しないもの（YAGNI）

- BM25 / TF-IDF
- Embedding / Vector Database (FAISS, Chroma等)
- Web検索 / Writeup自動収集
- Markdown, PDF, HTML, JSON等の解析
- 文章の要約 / Re-ranking
- OpenAI / Gemini API連携
- Controller / PromptManager 統合
- キャッシュ
