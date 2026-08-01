import re


class FlagExtractor:
    """AI回答文からフラグ候補を抽出するクラス"""

    _PATTERN = re.compile(r"(?:FLAG|flag|CTF|ctf)\{[^}]+\}")

    def extract(self, response: str) -> str | None:
        """
        回答テキストからフラグパターン(FLAG{...}, flag{...}, CTF{...}, ctf{...})を検索し、
        最初に見つかったフラグ文字列を返す。見つからない場合は None を返す。
        """
        match = self._PATTERN.search(response)
        if match:
            return match.group(0)
        return None
