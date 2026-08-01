# SPEC-024: End-to-End Integration Test

## 目的

Question入力からResultFormatterによる結果整形・出力までのシステム全体パイプラインが正常に連動して動作することを確認する。

## 概要

`pytest` を利用し、`FakeAIClient` によるスタブ化を行った上で、各カテゴリ（Crypto, Web, Rev, Unknown）におけるパイプラインの結合テストを実施する。

## テスト対象パイプライン

Question
↓
Analyzer (カテゴリ判定)
↓
PromptManager (プロンプト生成)
↓
FakeAIClient (テスト用レスポンス生成)
↓
Judge
├ FlagExtractor
├ ConfidenceEstimator
├ ReasonExtractor
├ HypothesisExtractor
├ NextActionExtractor
└ GeminiPromptGenerator
↓
JudgeResult
↓
ResultFormatter (CLI表示整形)

## 確認項目

1. **Crypto テスト**
   - Category が `Crypto` と判定されること
   - `FlagExtractor` が `flag{test_flag}` を正常抽出すること
   - `ConfidenceEstimator` が正しくスコア（80%）を算出すること
   - `HypothesisExtractor` が Crypto 用の仮説文を返却すること
   - `NextActionExtractor` が Crypto 用のアクションリストを返却すること
   - `GeminiPromptGenerator` がプロンプトを生成すること
   - `ResultFormatter` が整形済み文字列を出力すること

2. **Web テスト**
   - Category が `Web` と判定されること
   - Web 用の仮説文およびアクションリストが取得されること

3. **Rev テスト**
   - Category が `Rev` と判定されること
   - Rev 用の仮説文およびアクションリストが取得されること

4. **Unknown テスト**
   - Category が `Unknown` と判定されること
   - Unknown 用の仮説文およびアクションリスト（フォールバック）が取得されること

## 今回実装しないもの（YAGNI）

- 実API通信（OpenAI, Gemini, Claude等）
- RAG
- Retry
- Self Correction
- ベンチマーク・負荷試験
- APIコスト計測
- GUIテスト
