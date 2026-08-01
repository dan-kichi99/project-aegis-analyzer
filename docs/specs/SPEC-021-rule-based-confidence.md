# SPEC-021: Rule-based Confidence Estimator

## 目的

`ConfidenceEstimator` の固定値 `100` を廃止し、簡易ルールベースで信頼度（`confidence`）を算出する。

## 概要

フラグの有無および応答テキスト内の不確実表現の有無に基づいてスコアを可算・減算し、0〜100の範囲で信頼度を推定する。

## 入力

- `category`: str
- `response`: str
- `flag`: str | None

## 出力

- int (0〜100)

## スコアリングルール

1. **初期値**: 50
2. **フラグ加算**: `flag` が存在する場合（`None` でない場合）: +30
3. **不確実表現減算**: `response` 内に対象の不確実表現が1つ以上含まれる場合: -20
   - 対象語句: `"maybe"`, `"possibly"`, `"might"`, `"not sure"`, `"uncertain"`, `"probably"`（大文字小文字を区別しない）
4. **クランプ**: 算出結果を 0〜100 の範囲に収める

## 今回実装しないもの（YAGNI）

- AIによる信頼度評価
- カテゴリ別スコア
- 複数AI合議
- Judge AI
- RAG
- flag形式の高度な検証
- 推論整合性評価
- 再生成
- Self Correction
- 学習型スコアリング
