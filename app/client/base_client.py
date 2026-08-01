from abc import ABC, abstractmethod


class BaseAIClient(ABC):
    """AIクライアント共通インターフェース。"""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """プロンプトから回答文字列を生成する。"""
        raise NotImplementedError
