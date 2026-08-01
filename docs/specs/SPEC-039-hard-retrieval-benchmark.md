# SPEC-039: Hard Retrieval Benchmark

## 目的

現在の Real Knowledge Dataset に対する評価では Hit Rate 100% を達成しているが、キーワードの一致率が高いために難易度が低い可能性がある。
TASK-039 では、キーワードの直接一致を避け、表現揺れ・間接的な説明・略語・ノイズ情報等を含む Hard Benchmark ケース群を追加し、現在の検索ロジック（キーワード/BM25型検索）における限界や弱点を定量的に測定・把握する。

## Hard Benchmark の意義

実戦 CTF におけるユーザーからの自然言語問い合わせや障害調査クエリは、必ずしもナレッジ本文のキーワードと厳密に一致するとは限らない。本ベンチマークにより、同義語・説明的表現・ノイズが含まれるクエリに対する検索アルゴリズムの堅牢性と不適合ケースを可視化する。

## 構成と仕様

### ケース数およびカテゴリ構成
- 全ケース数: 最低 16 ケース（今回は各カテゴリ 4 ケースの計 16 ケース）
- カテゴリ内訳:
  - `Category.CRYPTO`: 4 ケース
  - `Category.WEB`: 4 ケース
  - `Category.REV`: 4 ケース
  - `Category.MISC`: 4 ケース

### Query 設計方針
キーワードの単純な直接コピーを排除し、以下の要素を組み合わせた高難易度クエリを作成する。
1. **別表現 / 概念的説明**: キーワード名を直接使わず、現象や手順を説明（例: "RSA modulus factors are almost the same size and very near each other"）
2. **同義語・関連概念**: "RSA" や "Fermat" といった決定的な単語を削り、類似の表現を使用
3. **ノイズ情報**: チャレンジのコンテキストや不要な背景情報の挿入
4. **複合技術クエリ**: 複数の概念が混ざった問いかけ

### 最低合格要件
- ケース数: `len(HARD_CASES) >= 16`
- 各カテゴリケース数: Crypto >= 4, Web >= 4, Rev >= 4, Misc >= 4
- **Hit Rate 最低基準**: `>= 0.50` (50.0%)
  ※本ベンチマークは弱点把握を主目的とするため、あえて高難易度に設定している。

## 検索ロジック変更禁止方針

本タスクの目的は弱点発見にあるため、テストを通す目的でクエリを平易化することや、以下の既存検索エンジンコンポーネントを変更することは厳重に禁止する。
- `KnowledgeRetriever`
- `TextNormalizer`
- `TextChunker`
- `DuplicateChunkFilter`
- `KnowledgeBudgetLimiter`

## 今回実装しないもの（YAGNI）

- Semantic Search / Embedding / Vector DB (FAISS, Chroma)
- Query Expansion / 同義語辞書 (Synonym dictionary)
- AI Re-ranking / RAG 改善
- BM25 パラメータ調整 / Normalizer 改修
- Web 検索 / 自動チューニング
