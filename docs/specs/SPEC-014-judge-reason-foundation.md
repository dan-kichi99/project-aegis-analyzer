# SPEC-014: Judge Reason Foundation

## 目的

JudgeResultの `reason` フィールドを利用できるようにする。

## 責務

- `Judge.evaluate()` で `reason` を設定する
- `answer` は従来どおり保持する
- `response` 全文を `reason` へ格納する

## 処理フロー

1. `OpenAIClient.generate(prompt)`
2. `response` 取得
3. `Judge.evaluate(category, response)`
4. `JudgeResult` 生成
5. `answer` へ `response` 格納
6. `reason` へ `response` 格納
7. `Controller` へ返却

## 依存コンポーネント

- `app.judge.judge_result.JudgeResult`

## 今回実装しないもの（YAGNI）

- フラグ抽出
- Confidence (信頼度) 計算
- Hypothesis (仮説)
- NextActions (次に試すこと)
- Gemini Prompt
- JSON 解析
- 正規表現解析
- AI 再生成
- Self Correction (自己修正)
