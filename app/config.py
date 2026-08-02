import os


class Config:
    """環境変数からProject Aegisの設定を読み込む。"""

    def __init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key or not api_key.strip():
            raise ValueError(
                "OPENAI_API_KEYが設定されていません。"
            )

        self.openai_api_key = api_key.strip()

        model = os.getenv("OPENAI_MODEL")

        self.openai_model = (
            model.strip()
            if model and model.strip()
            else "gpt-4o-mini"
        )