# SPEC-048: File Input Foundation

## 目的
添付ファイル（.exe, .elf, .zip, .png, .txt 等）を安全に読み込み、後続処理へ渡すための共通データ構造 (`FileInput`) およびローダー (`FileLoader`) を提供する。

## 設計構造
- `FileInput`: `@dataclass(slots=True)`。`name`, `path`, `size`, `extension`, `content` (`bytes`) を保持。
- `FileLoader`: 静的なバイト読み込み (`read_bytes()`) に限定し、存在しないパス (`FileNotFoundError`) やディレクトリ (`ValueError`) を厳格に拒否。

## セキュリティ方針
信用できない入力ファイルに対し、実行・展開・評価（subprocess, eval, zip extract 等）を一切行わず、メモリ上への静的読込のみに限定。

## Non-goals (YAGNI)
- MIME判定 / Magic Number解析 / MIME判定
- アーカイブ自動展開 / 逆コンパイル / 文字列抽出 / OCR
- Controller や CLI への統合（次タスク以降で実施）
