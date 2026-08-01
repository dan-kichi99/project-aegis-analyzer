# SPEC-023: Result Formatter Foundation

## 目的

`JudgeResult` の情報を大会中に確認しやすいCLI向け表示フォーマットへ整形する。

## 概要

`ResultFormatter` を新規追加し、`main.py` から表示整形の責務を分離する。

## 責務

- `JudgeResult` を受け取る
- CLI向けの表示用文字列へ変換する
- `None` や空リストに対するフォールバック表示の提供
- `next_actions` の番号付きリスト表示

## 入力

- `result`: JudgeResult

## 出力

- str

## 今回実装しないもの（YAGNI）

- Richライブラリ利用
- 色付き表示
- GUI
- Web UI
- JSON出力
- ファイル保存
- ログ保存
- Markdown保存
- クリップボードコピー
- Flag自動提出
- Retryボタン
- Gemini API
- Claude API
