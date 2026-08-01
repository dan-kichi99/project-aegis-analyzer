# SPEC-020: Gemini Prompt Generator Foundation

## 目的

`JudgeResult.gemini_prompt` を利用可能にする。

## 概要

Geminiへ渡すためのプロンプト生成処理を、Judgeから独立したコンポーネント `GeminiPromptGenerator` として追加し、`JudgeResult.gemini_prompt` へ格納する。

## 責務

- `GeminiPromptGenerator` の提供
- `category` / `response` からGemini向けプロンプトを生成
- `Judge` へのDI（依存注入）統合
- `JudgeResult.gemini_prompt` へ格納

## 入力

- `category`: str
- `response`: str

## 出力

- str

## 処理フロー

1. `Judge.evaluate(category, response)` 呼び出し
2. `GeminiPromptGenerator.generate(category, response)` の実行
3. `gemini_prompt` の取得
4. `JudgeResult(..., gemini_prompt=gemini_prompt)` の生成と返却

## 今回実装しないもの（YAGNI）

- Gemini API呼び出し
- GeminiClient
- Claude連携
- OpenAI追加呼び出し
- 自動コード実行
- フィルタ回避ロジック
- Jailbreak用プロンプト
- RAG
- Tool Calling
- Retry
- Self Correction
