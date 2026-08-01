# SPEC-007: Application Entry Point 実装

## 目的

Project Aegisのアプリケーションエントリーポイントを実装し、コンポーネント群を初期化・接続してユーザーからの質問に対するAIの回答を出力する。

## 責務

- 各依存コンポーネントを生成・接続する。
- ユーザー入力を受け取りControllerへ渡す。
- AIの回答を表示する。

## 実行方法

- python app/main.py

## 処理フロー

1. Config生成
2. OpenAIClient生成
3. PromptManager生成
4. Controller生成
5. input()
6. controller.process()
7. print()

## 依存コンポーネント

- Config
- OpenAIClient
- PromptManager
- Controller

## 今回実装しないもの（YAGNI）

- GUI
- CLIライブラリ
- Analyzer
- Judge AI
- ログ
- 会話履歴
- 例外処理
