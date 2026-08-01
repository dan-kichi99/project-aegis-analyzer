# SPEC-018: NextAction Extractor Foundation

## 目的

Judgeから `next_actions`（次に試すこと）の抽出・生成処理を切り離し、独立したコンポーネントとして追加する。

## 概要

`NextActionExtractor` クラスを新規追加し、`Judge` へ依存注入（DI）して取得したアクションリストを `JudgeResult.next_actions` に格納する。

## 責務

- `NextActionExtractor` クラスの提供
- 応答テキスト（`response`）からの `next_actions` の抽出（現段階では空のリスト `[]` を返却）
- `Judge` への `NextActionExtractor` の DI 統合
- 抽出結果を `JudgeResult.next_actions` へ設定

## 処理フロー

1. `main.py` で `NextActionExtractor` インスタンスを生成し、`Judge` へ注入
2. `Judge.evaluate(category, response)` 呼び出し
3. `NextActionExtractor.extract(response)` の実行
4. `JudgeResult` 生成時に `next_actions` を設定して返却

## 依存コンポーネント

- なし

## 今回実装しないもの（YAGNI）

- AIによる提案生成
- カテゴリ別分岐
- JSON解析
- Tool Calling
- Gemini連携
- Claude連携
- RAG
- 自己修正
- コマンド生成
- CTF解法生成
