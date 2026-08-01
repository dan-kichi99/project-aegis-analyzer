# SPEC-022: Rule-based Guidance

## 目的

`HypothesisExtractor` と `NextActionExtractor` へ最小限のカテゴリ別ガイダンスロジックを追加する。

## 概要

フラグが取得できない場合でも、カテゴリに応じた固定の仮説（Hypothesis）および次に確認すべき項目（NextActions）を返却する。

## 責務

- **HypothesisExtractor**: カテゴリに基づいて簡易仮説文字列（`str`）を返却する。
- **NextActionExtractor**: カテゴリに基づいて次に試すべきアクションリスト（`list[str]`）を返却する。

## 入力

- `category`: str
- `response`: str

## 出力

- **Hypothesis**: str
- **NextActions**: list[str]

※ 現段階では `response` の内容解析は行わず、カテゴリに基づく固定メッセージを返却する。

## 今回実装しないもの（YAGNI）

- AIによる仮説生成
- responseの意味解析
- RAG
- Writeup検索
- Gemini API
- Claude API
- 自動コード生成
- Tool Calling
- 自動コマンド実行
- Retry
- Self Correction
- flagの正誤判定
- 高度なカテゴリ分類
- 複数仮説ランキング
