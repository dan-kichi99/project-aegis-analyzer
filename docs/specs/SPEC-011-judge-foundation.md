# SPEC-011: Judge Foundation 実装

## 目的

Judge基盤を追加し、Controllerへ統合する。

## 責務

- `Judge` クラスの生成
- `Controller` への `Judge` の依存注入（DI）
- `process()` 内での `evaluate()` 呼び出しおよび評価対象テキストのパイプライン化

## 処理フロー

1. `Controller.process(question)` 呼び出し
2. `Analyzer.analyze(question)` による `category` 取得
3. `PromptManager.build(question, category)` による `prompt` 構築
4. `OpenAIClient.generate(prompt)` による `response` 取得
5. `Judge.evaluate(response)` の実行（今回はそのまま `response` を返却）
6. 最終結果の返却

## 依存コンポーネント

- なし (`Judge` 単体)

## 今回実装しないもの（YAGNI）

- 回答評価ロジック
- 信頼度スコアリング
- フラグ判定
- JSON フォーマット化・パース処理
- 複数 AI による検証
- AI への再質問・再生成
- 自己修正 (Self-Correction) ループ
