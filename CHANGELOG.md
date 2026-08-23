# Changelog

## v1.0.0

Initial Stable Release

### Analysis

- ZIP / TAR / GZIP Archive解析（Child File再帰解析・Path Traversal検出）
- PNG / JPEG / PDF / WAV 静的解析（Metadata・Signature・末尾追加データ）
- PE / ELF 解析（Section/Segment・EntryPoint・Overlay候補）
- Python / Java Source Code解析
- ASCII / UTF-16LE Strings抽出・Metadata・Appended Data検出
- RSA / XOR / Caesar / 再帰エンコード / Universal Encoding解析

### Application

- Tkinter GUI（入力・進捗・結果・Agent結果・承認・Budget表示）
- Flag候補検出とClipboard Copy
- Challenge Context生成
- Crypto、Rev、Web、Forensics専門AgentとJudgeによる解析Pipeline
- 承認付き生成コード実行
- Policy制御された外部Tool連携
- 反復解析とBudget管理
- CLI、GUI、環境診断Entry Point
- Challenge単位のAI使用量計測と重複通信抑止

### Safety

- Archive Path Traversal対策（ZIP/TAR、絶対パス・親ディレクトリ脱出の拒否）
- Policy制御された外部Tool Allowlist
- User承認なしの生成コード無断実行禁止
- 実行のTimeout・Subprocess分離・stdin無効化・環境変数非継承
- Parser例外を外部へ漏らさないFailure-Safe解析

### Quality

- 再現可能なBenchmarkおよびFailure Safety検証
- 自動Test 2098件以上（pytest）
- Ruff Lint：All checks passed
- 実API通信・実Tool起動を伴わないRelease Validation
- Windows実機GUI Smoke Test：PASS
- CLI Graceful Failure回帰Test（OPENAI_API_KEY未設定 / OpenAIError）
