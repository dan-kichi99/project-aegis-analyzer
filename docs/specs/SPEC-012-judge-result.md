# SPEC-012: JudgeResult DTO 実装

## 目的

Judgeが文字列ではなく `JudgeResult` オブジェクトを返却できるようにする。

## 概要

`JudgeResult` データ構造(DTO)を導入し、`Judge` の返却値を更新する。

## JudgeResult 保持情報

- `category`: カテゴリ名
- `answer`: 回答テキスト
- `flag`: フラグ文字列（任意）
- `confidence`: 信頼度（任意）
- `reason`: 評価理由（任意）
- `hypothesis`: 仮説（任意）
- `next_actions`: 次に試すことのリスト（任意）
- `gemini_prompt`: Gemini用プロンプト（任意）

## 処理フロー

1. `Controller.process(question)` 呼び出し
2. `Analyzer.analyze(question)` による `category` 取得
3. `PromptManager.build(question, category)` による `prompt` 構築
4. `OpenAIClient.generate(prompt)` による `response` 取得
5. `Judge.evaluate(response)` を実行し、`JudgeResult` オブジェクトを取得
6. `main.py` にて `result.answer` を表示

## 今回実装しないもの（YAGNI）

- フラグ抽出
- Confidence（信頼度）計算
- JSON生成・パース処理
- Gemini 連携
- Claude 連携
- RAG (Retrieval-Augmented Generation)
- Tool Calling
- Self Correction（自己修正）
- 再生成
- 推論ロジック
