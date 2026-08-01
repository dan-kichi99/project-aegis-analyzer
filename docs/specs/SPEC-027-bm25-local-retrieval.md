# SPEC-027: BM25 Local Knowledge Retrieval

## 目的

`KnowledgeRetriever` のローカルテキスト検索処理を、単純な単語出現回数カウントから Python 標準ライブラリのみで実装する BM25 ランキングアルゴリズムへ強化する。

## 概要

外部APIやVector DB、外部ライブラリを追加せず、`data/knowledge/` 配下の `.txt` ファイル群に対して完全ローカルで BM25 スコアを算出・ランキングを行う。

## BM25 仕様

### 定数パラメータ
- `_K1 = 1.5`
- `_B = 0.75`

### 数式・計算要素
- **文書数 $N$**: 対象カテゴリ内の有効な `.txt` ファイル総数
- **平均文書長 $avgdl$**: 対象文書群の単語数の平均値（ゼロ除算防止）
- **IDF (Inverse Document Frequency)**:
  $$\text{IDF}(q_i) = \ln\left(\frac{N - n(q_i) + 0.5}{n(q_i) + 0.5} + 1\right)$$
  ※ $n(q_i)$ は単語 $q_i$ を含む文書数
- **BM25 Score**:
  $$\text{Score}(D, Q) = \sum_{q_i \in Q} \text{IDF}(q_i) \cdot \frac{f(q_i, D) \cdot (k_1 + 1)}{f(q_i, D) + k_1 \cdot \left(1 - b + b \cdot \frac{|D|}{avgdl}\right)}$$
  ※ $f(q_i, D)$ は文書 $D$ 内の単語 $q_i$ の出現頻度（tf）

## トークン化
1. 小文字化（`.lower()`）
2. 空白分割（`.split()`）
※ 形態素解析や高度な自然言語処理は行わない。

## 検索ルール
1. `query` およびファイルをトークン化
2. スコア算出後、`Score <= 0` の文書を除外
3. スコア降順でソートし、上位最大3件の本文テキスト（`list[str]`）を返却

## 例外・空データ処理
- `query` が空、対象ディレクトリ不在、対象 `.txt` ファイルが0件の場合は `[]` を返却
- ファイル読み込み時の `UnicodeDecodeError` および `OSError` はスキップ処理

## 今回実装しないもの（YAGNI）
- 外部BM25ライブラリ (rank_bm25等)
- Embedding / Vector DB (FAISS, Chroma等)
- 形態素解析・N-gram
- RAG統合 / Controller統合 / PromptManager統合
