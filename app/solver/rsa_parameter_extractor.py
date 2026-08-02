import re

from app.solver.rsa_result import RsaParameters

MAX_PARAMETER_CHARACTERS = 4_096
_PARAMETER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(n|e|c|p|q|d|phi)(?![A-Za-z0-9_])"
    r"\s*[:=]\s*(0[xX][0-9A-Fa-f]+|[0-9]+)",
    re.IGNORECASE,
)


class RsaParameterExtractor:
    """単一入力ブロックから曖昧でないRSA代入表記を抽出する。"""

    def extract(self, text: str, source: str) -> RsaParameters | None:
        values: dict[str, int] = {}
        for match in _PARAMETER_PATTERN.finditer(text):
            name = match.group(1).casefold()
            raw_value = match.group(2)
            if len(raw_value) > MAX_PARAMETER_CHARACTERS:
                return None
            if name not in values:
                values[name] = int(raw_value, 0)

        if not values:
            return None
        return RsaParameters(source=source, **values)
