# SPEC-006: OpenAI Integration 実装

## 目的
OpenAI API（Chat Completions API）と通信を行い、構築されたプロンプトに対してAIからの応答文字列を取得する。

## 責務
- `Config` から APIキーおよび使用モデル名を取得し、OpenAIクライアントを初期化する。
- 受け取ったプロンプトを `user` メッセージとして送信し、AIの返答テキストを返す。

## 入力
- `prompt` (str): AIモデルへ送るプロンプト文字列

## 出力
- `response` (str): AIモデルから返却されたレスポンス本文（テキスト）

## 依存コンポーネント
- `Config` (`app.config.Config`)
- `openai` (`openai.OpenAI`)
- `BaseAIClient` (`app.ai.base.BaseAIClient`)

## 今回実装しないもの（YAGNI）
- Streaming（ストリーミング出力）
- Retry（自動リトライ処理）
- Timeout（タイムアウト設定）
- Temperature / Max Tokens 等の追加パラメータ指定
- Function Calling / Tool Call
- Structured Output（構造化出力）
- 画像・音声等のマルチモーダル入力
- Analyzer / Judge AI 等の高度な処理
