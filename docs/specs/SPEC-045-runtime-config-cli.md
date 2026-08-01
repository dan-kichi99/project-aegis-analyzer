# SPEC-045: Runtime Config + CLI Wiring

## 目的

`os.getenv()` を用いて環境変数からランタイム設定（`OPENAI_API_KEY`, `OPENAI_MODEL`）を読み込む `Config` クラスを導入し、`main.py` を通じて CLI から実際の AI 回答生成パイプラインを一貫して呼び出せる状態を構築する。

## 設定仕様 (`Config`)

| 環境変数名 | 必須 / 任意 | デフォルト値 | 未設定・空文字列時の挙動 |
| :--- | :--- | :--- | :--- |
| `OPENAI_API_KEY` | **必須** | なし | `ValueError("OPENAI_API_KEY is not configured.")` を送出 |
| `OPENAI_MODEL` | 任意 | `"gpt-4o-mini"` | デフォルト値 `"gpt-4o-mini"` を採用 |

※ `python-dotenv` などのサードパーティ製ライブラリは使用せず、標準ライブラリの `os.getenv()` のみを使用する。

## CLI 処理フロー (`main.py`)

1. `Config()` のインスタンス化（環境変数の検証と読み込み）
2. `OpenAIClient(api_key=config.openai_api_key, model=config.openai_model)` の初期化
3. `Controller(ai_client=ai_client)` の初期化
4. CLI 入力受領: `question = input("Question:\n")`
5. パイプライン実行: `result = controller.process(question)`
6. 結果出力: `ResultFormatter().format(result)` を用いて整形し、`print()` で出力

## テストおよび API 課金防止方針

- `test_config.py`: `monkeypatch.setenv` / `delenv` を用いて環境変数の存在・欠損パターンを安全に検証。
- `test_main.py`: `unittest.mock.patch` により `OpenAIClient` および `input()` を完全にモック化し、実 API 通信を 0 回に抑えた上で CLI の入出力フローを検証。

## YAGNI 違反の防止（今回実装しないもの）

- `python-dotenv` 依存追加 / JSON・YAML 設定ファイル対応
- CLI フレームワーク（`click`, `argparse`, `typer` 等）の導入
- Key Rotation / Secret Manager 連携 / Dynamic Config Reloading
- Multi-provider 設定 (Gemini / Claude 等)
