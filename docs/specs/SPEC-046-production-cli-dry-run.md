# SPEC-046: Production CLI Dry Run

## 目的

本番環境での実際の API 接続前における最終ドライランとして、AI Client 以外のすべての本番コンポーネント（`Controller`, `Analyzer`, `KnowledgeRetriever`, `PromptManager`, `Judge`, `ResultFormatter`）を本番同様に結合し、パイプライン全体が正しく動作することを確認する。

## 実コンポーネント構成と FakeAIClient の役割

ドライランでは以下のように本番パイプラインを組み立てる。

[Question]
│
▼
Controller
├─► Analyzer (カテゴリ判定)
├─► KnowledgeRetriever (ローカルナレッジ検索)
├─► PromptManager (カテゴリ別プロンプト構築)
├─► FakeAIClient (生成AIの応答をシミュレート)
├─► Judge (Flag抽出・確信度計算・次アクション決定)
└─► ResultFormatter (出力フォーマット整形)


`FakeAIClient` は `BaseAIClient` インターフェースを実装したテスト専用クラスであり、送信されたプロンプト文字列を保持しつつ事前に用意したダミーテキストを返却する。`OpenAIClient` を使用しないため、実 API キー不要・ネットワーク通信 0 回・課金 0 円での検証が可能となる。

## 他タスク (TASK-043, 044, 045) との役割の違い

- **TASK-043**: `Controller` 単位での E2E 結合の基本検証。
- **TASK-044**: `OpenAIClient` 単体での API キー受領・エラーハンドリング・SDK 連携モック検証。
- **TASK-045**: 環境変数（`Config`）および `main.py` の CLI 結合テスト。
- **TASK-046 (本タスク)**: `app/data/knowledge` の実データを使用した、本番に極めて近い実コンポーネント全体結合ドライラン。

## YAGNI 違反の防止

- 既存の本番コード（`app/`）の変更・改修は一切行わない。
- 新機能、Retry、Streaming、Async、Web UI、CLI フレームワーク等の追加は一切行わない。
