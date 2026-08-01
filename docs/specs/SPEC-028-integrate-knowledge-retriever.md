cat << 'EOF' > docs/specs/SPEC-028-integrate-knowledge-retriever.md
# SPEC-028: Integrate KnowledgeRetriever into Controller

## 目的

BM25を用いたローカル知識検索機能 `KnowledgeRetriever` を既存の質問処理パイプライン（Controller / PromptManager）へ統合する。

## 概要

無料のローカル検索処理で事前にコンテキスト情報を絞り込み、その結果をプロンプトに挿入してAIクライアントに渡すことで、外部検索やEmbeddingコストを発生させずに問題解決の精度向上を図る。

## 変更後の処理フロー（データフロー）

Question
  ↓
Analyzer (カテゴリ判定)
  ↓
KnowledgeRetriever (ローカルBM25知識検索)
  ↓ knowledge: list[str]
PromptManager (質問・カテゴリ・ローカル知識を統合したプロンプト作成)
  ↓ prompt: str
AIClient (推論実行)
  ↓ response: str
Judge (判定・スコアリング・分析)
  ↓
ResultFormatter (整形出力)

## 責務

- **Controller**:
  - `KnowledgeRetriever` を依存性注入 (DI) で受容
  - `Analyzer` ➔ `KnowledgeRetriever` ➔ `PromptManager` ➔ `AIClient` ➔ `Judge` の連携を正しく順序立てて実行
- **PromptManager**:
  - `build(question, category, knowledge)` メソッドにて、`knowledge`（ローカル知識テキスト群）を受け取る
  - プロンプトの末尾に `Relevant local knowledge:` セクションを追加し、コンテキスト情報を挿入（空の場合は `"No local knowledge available."`）

## 今回実装しないもの（YAGNI）

- Embedding / Vector DB / FAISS
- Re-ranking / 知識のAI自動圧縮 / トークン数最適化
- Web検索 / Writeup自動取得
- キャッシュ機能
- 多段階検索 (Multi-stage Retrieval)
EOF
