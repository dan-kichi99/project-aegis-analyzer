# SPEC-050: Static File Feature Extraction

## 目的
`FileInput` および `FileTypeDetector` の判定結果を受け、ローカルファイルを一切実行することなく、安全に型情報・テキスト内容・ASCII printable strings（最大200件）などの静的特徴を抽出する。

## 静的特徴抽出仕様
1. **解析制限**: CPU・メモリ過負荷防止のため先頭 `2,000,000` バイト (2MB) のみを解析。
2. **Text抽出**: `detected_type == "text"` の場合のみ UTF-8 decode を試行。失敗時は `None`。
3. **Printable Strings抽出**:
   - Python標準機能のみを用いて ASCII 範囲 (`0x20` 〜 `0x7E`) の連続文字を抽出。
   - 最小文字数: 4文字。
   - 最大件数制限: 200件。

## 責務分離
- `FileLoader`: 静的なファイル読込
- `FileTypeDetector`: Magic Bytes 等に基づく形式同定
- `StaticFileAnalyzer`: 読み込まれたデータからの安全な静的特徴抽出

## Non-goals (YAGNI)
- PE/ELF ヘッダー解読、ZIP解凍、PDF本文解析、EXIF/OCR解析
- 外部コマンド (`strings` コマンドや `binwalk` 等) の実行
- パイプライン (`Controller`) への統合
