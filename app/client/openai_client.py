from openai import OpenAI

from app.client.base_client import BaseAIClient


class OpenAIClient(BaseAIClient):
    """OpenAI APIを利用する本番用AIクライアント。"""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("API key must be provided.")

        self._model = model
        self._client = OpenAI(api_key=api_key)

    def generate(self, prompt: str) -> str:
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
            raise RuntimeError(
                "OpenAI API returned an empty response."
            )

        content = response.choices[0].message.content

        if content is None:
            raise RuntimeError(
                "OpenAI API returned a choice with no content."
            )

        return content
