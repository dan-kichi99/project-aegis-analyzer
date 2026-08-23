# Project Aegis v1.0.0 Release Checklist

- [x] pytest成功（2098 passed）
- [x] Ruff成功（All checks passed）
- [x] git diff --check成功
- [x] Git working tree確認（Tracked Fileは変更なし。未Tracked空File`=`が残存 — Issue参照）
- [x] GUI起動（Windows実機Smoke Test PASS）
- [x] CLI起動
- [x] Diagnostics起動
- [x] Benchmark成功
- [x] Failure Safety Test成功
- [x] README確認
- [x] `.env.example`確認
- [x] `.gitignore`確認
- [x] APIキー・Token・個人Pathを含まないこと
- [x] 実API通信・実Tool起動を伴わないRelease Validation成功

## 追加確認項目（Portfolio Polish / Release最終確認）

- [x] Archive Safety（Path Traversal・Corrupt Archive・Nested Archive）
- [x] External Execution Safety（承認Flow・外部Tool Allowlist・Iteration Budget制御）
- [x] Secret Scan（Tracked File全件、Screenshot埋め込みStrings含む）
- [x] Screenshots掲載（`docs/images/aegis-main.png`、`docs/images/aegis-analysis-result.png`）
- [x] Demo documentation（`docs/DEMO.md`、自作Sampleのみ使用・第三者CTF著作物なし）
- [x] Flag Copy動作確認（Windows実機Smoke Test）
- [x] CLI：`OPENAI_API_KEY`未設定時のGraceful Failure（回帰Testで固定済み）
- [x] CLI：OpenAIError発生時のGraceful Failure（回帰Testで固定済み）
