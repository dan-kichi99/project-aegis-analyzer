# SPEC-043: Answer Generation Integration

## 目的

TASK-042までに構築・最適化された Knowledge 検索基盤（`KnowledgeRetriever`）を、既存の AI 回答生成パイプライン（`Controller` $\rightarrow$ `PromptManager` $\rightarrow$ `AIClient` $\rightarrow$ `Judge`）へ正式に統合接続し、ナレッジの有無に応じたプロンプト構築および最終回答判定がエンドツーエンドで安定して機能することを検証・保証する。

## 処理フローとコンポーネントの責務

全体の統合フローは以下の順序を厳密に遵守する。

Question (入力)
│
▼

Analyzer.analyze(question) ──► Category 決定
│
▼

KnowledgeRetriever.retrieve(category, question) ──► Knowledge Chunk リスト取得
│
▼

PromptManager.build(question, category, knowledge) ──► 最終プロンプト文字列生成
│
▼

AIClient.generate(prompt) ──► AI 回答テキスト生成
│
▼

Judge.evaluate(category, response) ──► JudgeResult (is_correct, category, flag)


### 各コンポーネントの責務

| コンポーネント | 責務 |
| :--- | :--- |
| **`Controller`** | パイプライン全体を制御し、データの受け渡し順序（1～5）を調整・統一する。 |
| **`Analyzer`** | 入力テキストからカテゴリ（`CRYPTO`, `WEB`, `REV`, `MISC`, `UNKNOWN`）を分類。 |
| **`KnowledgeRetriever`** | クエリ拡張・Stopword除去・BM25検索・Zero-Match判定を経て関連ナレッジを抽出。 |
| **`PromptManager`** | カテゴリとナレッジの有無（あり: `Relevant local knowledge:`, なし: `No local knowledge available.`）に応じてシステムプロンプトを構築。 |
| **`BaseAIClient`** | 構築されたプロンプトを受け取り、AI回答テキストを生成（テスト時は `FakeAIClient` を使用）。 |
| **`Judge`** | カテゴリと AI の回答テキストから、Flag の抽出および判定結果（`JudgeResult`）を出力。 |

## Knowledge あり / なし / Zero-Match 時の挙動

### 1. Knowledge が存在する場合
- `KnowledgeRetriever` から 1 つ以上のチャンクが返却された場合。
- `PromptManager` はプロンプト内に `Relevant local knowledge:` セクションを形成し、ナレッジ本文を挿入する。

### 2. Knowledge が空 / Zero-Match の場合
- 入力クエリが完全無関係（例: `"quantum spaceship banana"`）、Stopword のみ、あるいは BM25 スコアが全件 0.0 の場合（TASK-041 / TASK-042）。
- `KnowledgeRetriever` は空リスト `[]` を返却する。
- `PromptManager` はプロンプト内のナレッジセクションに `"No local knowledge available."` を挿入し、コンテキスト汚染を防ぐ。

## E2E 確認項目

1. Crypto 質問時にナレッジが正しくプロンプト内に含まれていること。
2. Web / 検索ヒットなし質問時に `"No local knowledge available."` が入ること。
3. `FakeAIClient` へ渡されたプロンプト全文が正しく記録され、ナレッジの包含状態を検証できること。
4. `JudgeResult` の `category` および `flag` 抽出が正常に維持されること。
5. Query Expansion 経由の検索（例: `"RSA modulus factors are almost the same size"`）で、Fermat ナレッジが統合プロンプトへ組み込まれること。
6. Zero-Match クエリ（例: `"quantum spaceship banana"`）で `"No local knowledge available."` が出力されること。

## 今回実装しないもの（YAGNI）

- Retry / Auto Retry / Self Correction
- Multi-agent 構成
- 外部 API 接続 (Gemini / Claude API 等)
- Streaming 応答 / Web UI / GUI
- Agent Memory / Conversation History
- Tool Calling / Function Calling
- Re-ranking / Vector DB / Embedding 導入
