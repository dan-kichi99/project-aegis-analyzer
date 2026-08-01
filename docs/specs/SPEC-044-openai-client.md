# SPEC-044: OpenAI Client Production Implementation

## 目的

`BaseAIClient` を継承した本番環境用の LLM クライアント `OpenAIClient` を実装し、Project Aegis の回答生成パイプラインから実際の OpenAI API を安全に利用できる構造を整備する。

TASK-044 では、実 API 通信や課金が発生する処理は行わず、モック（Mock/Fake）を用いた単体テストによってインターフェースの互換性とクライアント動作を保証する。

## クラス構造と BaseAIClient との関係

`Controller` は具体クラスである `OpenAIClient` の存在を直接意識せず、抽象基底クラス `BaseAIClient` の `generate(prompt: str) -> str` インターフェースを通じてやり取りを行う。

Controller
│
▼
BaseAIClient (抽象インターフェース)
▲
│ (継承)
OpenAIClient (本番用実装)


## OpenAIClient の責務・仕様

### コンストラクタ (`__init__`)
```python
def __init__(self, api_key: str, model: str = "gpt-4o") -> None:
api_key: コンストラクタ DI により受け取る。ソースコードへのハードコードは厳禁とし、呼出側（環境変数等）から渡される。

model: コンストラクタ DI により指定。

生成処理 (generate)
Python
def generate(self, prompt: str) -> str:
OpenAI SDK の client.chat.completions.create() を呼び出す。

レスポンスからテキスト抽出を行って文字列 str で返却する。

エラーハンドリング
API レスポンスが空（None）または本文テキストが存在しない場合、RuntimeError("OpenAI API returned an empty response.") を送出する。

テスト方針・API料金が発生しない理由
tests/test_openai_client.py では unittest.mock.MagicMock または unittest.mock.patch を使用して openai.OpenAI SDK クライアントを完全にモック化する。
実際のネットワーク通信および API キーの有効性チェックは行われないため、API 課金は 0 円であり、CI/CD やローカル環境で高速かつ安定して実行可能。

YAGNI 違反の防止（今回実装しないもの）
Streaming 応答

Retry / Exponential Backoff

Async / Non-blocking 処理

Multi-provider (Gemini, Claude 等)

Tool Calling / Function Calling

Response Cache / Rate Limit Manager / Token Counter / Cost Tracker


---

### 2. `app/client/openai_client.py`（新規作成）

```python
from openai import OpenAI

from app.client.base_client import BaseAIClient


class OpenAIClient(BaseAIClient):
    """OpenAI API を利用して回答テキストを生成する本番用 AI クライアント。"""

    def __init__(self, api_key: str, model: str = "gpt-4o") -> None:
        if not api_key or not api_key.strip():
            raise ValueError("API key must be provided.")

        self._model = model
        self._client = OpenAI(api_key=api_key)

    def generate(self, prompt: str) -> str:
        """指定されたプロンプトを OpenAI Chat Completions API に送信し、応答テキストを返す。"""
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        )

        if not response.choices:
            raise RuntimeError("OpenAI API returned an empty response.")

        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError("OpenAI API returned a choice with no content.")

        return content
