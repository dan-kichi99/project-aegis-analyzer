# SPEC-017: Reason Extractor Foundation

## 目的

Judgeから `reason`（解説・根拠）の抽出・加工処理を切り離し、独立したコンポーネント化を行う。

## 概要

`ReasonExtractor` クラスを新規追加し、`Judge` へ依存注入（DI）して取得した解説テキストを `JudgeResult.reason` に格納する。

## 責務

- `ReasonExtractor` クラスの提供
- 応答テキスト（`response`）からの `reason` の抽出（現段階では加工せずそのまま返却）
- `Judge` への `ReasonExtractor` の DI 統合
- 抽出結果を `JudgeResult.reason` へ設定

## 処理フロー

1. `main.py` で `ReasonExtractor` インスタンスを生成し、`Judge` へ注入
2. `Judge.evaluate(category, response)` 呼び出し
3. `ReasonExtractor.extract(response)` の実行
4. `JudgeResult` 生成時に `reason` を設定して返却

## 依存コンポーネント

- なし

## 今回実装しないもの（YAGNI）

- AI解析
- JSON解析
- 正規表現解析
- 自然言語解析
- 要約
- 自己修正
- Gemini連携
- Claude連携
