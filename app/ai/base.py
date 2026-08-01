from abc import ABC, abstractmethod


class BaseAIClient(ABC):
    """AI Clientの抽象基底クラス"""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """テキスト生成処理（派生クラスで実装）"""
        ...
