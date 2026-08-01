# SPEC-015: Flag Extractor Foundation

## 目的

JudgeがAIの回答文からフラグ候補を抽出できるようにする。

## 概要

`FlagExtractor` クラスを新規追加し、`Judge` へ依存注入（DI）して抽出結果を `JudgeResult.flag` に格納する。

## 責務

- `FlagExtractor` クラスの提供
- AIの応答テキスト（`response`）から基本的なフラグパターン（`FLAG{...}`, `flag{...}`, `CTF{...}`, `ctf{...}`）の抽出
- `Judge` への `FlagExtractor` の DI 統合
- 抽出結果を `JudgeResult.flag` へ設定

## 処理フロー

1. `main.py` で `FlagExtractor` インスタンスを生成し、`Judge` へ注入
2. `Judge.evaluate(category, response)` 呼び出し
3. `FlagExtractor.extract(response)` の実行
4. フラグ文字列（見つからない場合は `None`）の取得
5. `JudgeResult(category=category, answer=response, flag=flag, reason=response)` の生成と返却

## 依存コンポーネント

- `re` (標準ライブラリ)

## 今回実装しないもの（YAGNI）

- 正規表現の高度化・複雑化
- 複数フラグのランキング・重複排除
- Confidence (信頼度) 計算
- Reason (解説) 解析
- Hypothesis (仮説) 生成
- NextActions (次に試すこと) 生成
- Gemini / Claude 連携
- JSON パース
- AI による再判定・再生成
