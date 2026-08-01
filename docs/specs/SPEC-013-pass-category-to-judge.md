# SPEC-013: Analyzer Category を JudgeResult へ受け渡す

## 目的

Analyzerが判定したカテゴリを、JudgeResultまで保持できるようにする。

## 責務

- ControllerからJudgeへ `category` を渡す
- JudgeResultへ `category` を保存する
- データフローを一本化する

## 処理フロー

1. `Analyzer.analyze(question)`
2. `category` 取得
3. `PromptManager.build(question, category)`
4. `OpenAIClient.generate(prompt)`
5. `Judge.evaluate(category, response)`
6. `JudgeResult(category=category, answer=response)`
7. `main.py` へ返却

※ カテゴリは現時点では文字列 (`str`) として受け渡す。将来的に `Category` 型への置き換えを想定する。

## 依存コンポーネント

- `app.judge.judge_result.JudgeResult`

## 今回実装しないもの（YAGNI）

- フラグ抽出
- Confidence (信頼度) 計算
- Reason (根拠)
- Hypothesis (仮説)
- Gemini Prompt
- 再生成
- Self Correction (自己修正)
