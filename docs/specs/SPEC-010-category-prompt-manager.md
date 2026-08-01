# SPEC-010: Category-based PromptManager 実装

## 目的

Analyzerで判定したカテゴリを受け取り、カテゴリに応じた専用プロンプト（Prompt）を生成する。

## 責務

- カテゴリごとのプロンプトテンプレートの管理
- `build(question, category)` による最終プロンプト文字列の生成
- 未定義・未一致カテゴリ（`Unknown`）へのデフォルトテンプレート適用

## 処理フロー

1. `Controller` から `question` および `category` を受け取る。
2. 該当する `category` に対応するテンプレートを検索する。
3. テンプレートが存在しない場合は `Unknown` 用のテンプレートを選択する。
4. テンプレートの `{question}` 部分に `question` を埋め込んでプロンプトを構築し返却する。

## 依存コンポーネント

- なし

## 今回実装しないもの（YAGNI）

- Few-shot プロンプト
- RAG (Retrieval-Augmented Generation)
- Tool Calling
- Prompt のバージョン管理
- Prompt の外部ファイル化
- 動的 (Dynamic) Prompt 生成
- カテゴリ別 AI の切り替え
