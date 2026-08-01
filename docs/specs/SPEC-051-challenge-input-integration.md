# SPEC-051: Challenge Input Integration

## 目的
問題文および添付ファイルの解析結果 (`FileAnalysisResult`) を集約した DTO (`ChallengeInput`) を定義し、後続の AI 推論用コンテキスト文字列を安全かつ一定のフォーマットで生成するビルダー (`ChallengeContextBuilder`) を実装する。

## 出力フォーマット仕様
```text
Challenge Question:
<問題文>

Attached Files:
[File 1]
Name: <ファイル名>
Detected Type: <判定型>
Size: <サイズ> bytes
Extension: <拡張子>

Text Content:
<テキスト本文 または Not available>

Extracted Strings:
- <string1>
- <string2>
ファイルが存在しない場合は Attached Files:\nNone を出力する。

制限事項・動作仕様
問題文バリデーション: question.strip() が空文字の場合、ValueError を送出する。

Text Content 制限: 各ファイルのテキスト本文は最大 10,000 文字とし、超過時は先頭10,000文字の末尾に \n[truncated] を付与する。

Extracted Strings 制限: コンテキストに含める strings は最大 50 件とする。

非破壊性: FileAnalysisResult 内の元のデータ（text_content や strings）は一切変更せず、文字列整形時のみカットを行う。

複数ファイル: files リストの入力順序（[File 1], [File 2], ...）を保持する。

責務分離
ChallengeInput: 純粋な入力データの保持

ChallengeContextBuilder: コンテキスト文字列への整形・各種出力幅の制御

Non-goals (YAGNI)
Controller や PromptManager への接続

AI との通信、自動解析、ファイル再読み込み
