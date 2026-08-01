# SPEC-049: File Type Detection by Magic Bytes

## 目的
添付ファイルの拡張子に依存せず、ヘッダーの Magic Bytes (File Signature) を検証して実際のファイル形式を同定する。

## 対応判定形式と Magic Bytes
1. **PE**: `b"MZ"`
2. **ELF**: `b"\x7fELF"`
3. **PNG**: `b"\x89PNG\r\n\x1a\n"`
4. **JPEG**: `b"\xff\xd8\xff"`
5. **ZIP**: `b"PK\x03\x04"`, `b"PK\x05\x06"`, `b"PK\x07\x08"`
6. **PDF**: `b"%PDF-"`
7. **GIF**: `b"GIF87a"`, `b"GIF89a"`

## 判定優先順位
1. Magic Bytes マッチ判定
2. Empty 判定 (`len(content) == 0`)
3. UTF-8 Text 判定 (`decode("utf-8")` 成功かつ `\x00` なし)
4. Unknown (`"unknown"`)

## 安全方針および責務分離
- 静的バイト比較および UTF-8 decode 試行のみを行い、一切のコード実行やアーカイブ展開は行わない。
- 読込（`FileLoader`）と判定（`FileTypeDetector`）の責務を厳格に分離する。
