# SPEC-019: Hypothesis Extractor Foundation

## 目的

JudgeResult.hypothesisを利用できる基盤を作成し、仮説生成処理をJudgeから独立させる。

## 責務

- HypothesisExtractorの提供
- JudgeへのDI
- JudgeResult.hypothesisへの結果格納

## 入力

- category: str
- response: str

## 出力

- str | None (現段階では常にNone)

## 処理フロー

1. Judge.evaluate(category, response) 呼び出し
2. HypothesisExtractor.extract(category, response) の実行
3. hypothesis (None) の取得
4. JudgeResult(..., hypothesis=hypothesis) の生成と返却

## 今回実装しないもの（YAGNI）

- AIによる仮説生成
- カテゴリ別ロジック
- 回答解析
- 正規表現解析
- JSON解析
- RAG
- Gemini連携
- Claude連携
- Tool Calling
- Self Correction
- Retry
- 自動コード生成
