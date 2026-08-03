import re


class FlagExtractor:
    """AI回答文からフラグ候補を抽出するクラス"""

    _PATTERN = re.compile(r"(?:picoCTF|FLAG|flag|CTF|ctf)\{[^}]+\}")

    def extract(self, response: str) -> str | None:
        """
        回答テキストからフラグパターン(FLAG{...}, flag{...}, CTF{...}, ctf{...})を検索し、
        最初に見つかったフラグ文字列を返す。見つからない場合は None を返す。
        """
        matches = self.extract_all(response)
        return matches[0] if matches else None

    def extract_all(self, response: str) -> tuple[str, ...]:
        """既存Flag形式の候補を出現順・完全一致で重複排除して返す。"""
        candidates: list[str] = []
        seen: set[str] = set()
        for match in self._PATTERN.finditer(response):
            candidate = match.group(0)
            if candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)
        return tuple(candidates)
