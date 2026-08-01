from openai import OpenAI

from ..config import Config
from .base import BaseAIClient


class OpenAIClient(BaseAIClient):
    """OpenAI APIを利用してテキスト生成を行うクライアント"""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._client = OpenAI(api_key=self._config.openai_api_key)

    def generate(self, prompt: str) -> str:
        """
        プロンプトを受け取り、OpenAI Chat Completions APIを呼び出して返答テキストを返す
        """
        try:
            response = self._client.chat.completions.create(
                model=self._config.openai_model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
            )
            if not response.choices:
                return ""
            return response.choices[0].message.content or ""
        except Exception as e:
            raise RuntimeError(f"Failed to generate response: {e}") from e
