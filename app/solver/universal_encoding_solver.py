import base64
import binascii
import re

MAX_UNIVERSAL_ENCODING_INPUT = 20_000
MIN_ENCODED_LENGTH = 4

_BASE64_PATTERN = re.compile(r"[A-Za-z0-9+/]+={0,2}\Z")
_URLSAFE_BASE64_PATTERN = re.compile(r"[A-Za-z0-9_-]+={0,2}\Z")
_BASE32_PATTERN = re.compile(r"[A-Z2-7]+={0,6}\Z", re.IGNORECASE)
_BASE85_PATTERN = re.compile(r"[0-9A-Za-z!#$%&()*+\-;<=>?@^_`{|}~]+\Z")
_ASCII85_PATTERN = re.compile(r"(?:<~)?[!-u\s]+(?:~>)?\Z")
_HEX_PATTERN = re.compile(r"(?:[0-9A-Fa-f]{2}\s*)+\Z")
_BINARY_PATTERN = re.compile(r"(?:[01]{8}\s*){2,}\Z")
_OCTAL_PATTERN = re.compile(r"[0-7]{3}(?:\s+[0-7]{3})+\Z")
_DECIMAL_PATTERN = re.compile(r"\d{1,3}(?:\s*[, ]\s*\d{1,3})+\Z")


class UniversalEncodingSolver:
    """Decode bounded, text-only representations without external execution."""

    def decode(self, value: str) -> tuple[tuple[str, str], ...]:
        candidate = value.strip()
        if not candidate or len(candidate) > MAX_UNIVERSAL_ENCODING_INPUT:
            return ()
        decoded: list[tuple[str, str]] = []
        seen: set[str] = set()
        methods = (
            ("base64", self._base64),
            ("urlsafe_base64", self._urlsafe_base64),
            ("base32", self._base32),
            ("base85", self._base85),
            ("ascii85", self._ascii85),
            ("hex_ascii", self._hex),
            ("binary_ascii", self._binary),
            ("octal_ascii", self._octal),
            ("decimal_ascii", self._decimal),
        )
        for method, decoder in methods:
            output = decoder(candidate)
            if output is None or output == candidate or output in seen:
                continue
            seen.add(output)
            decoded.append((method, output))
        return tuple(decoded)

    @staticmethod
    def _utf8(data: bytes) -> str | None:
        try:
            value = data.decode("utf-8")
        except UnicodeDecodeError:
            return None
        if not value or any(
            not char.isprintable() and char not in "\r\n\t" for char in value
        ):
            return None
        return value

    def _base64(self, value: str) -> str | None:
        if len(value) < 8 or not _BASE64_PATTERN.fullmatch(value):
            return None
        padded = value + "=" * (-len(value) % 4)
        try:
            return self._utf8(base64.b64decode(padded, validate=True))
        except (binascii.Error, ValueError):
            return None

    def _urlsafe_base64(self, value: str) -> str | None:
        if (
            len(value) < 8
            or not ({"-", "_"} & set(value))
            or not _URLSAFE_BASE64_PATTERN.fullmatch(value)
        ):
            return None
        padded = value + "=" * (-len(value) % 4)
        try:
            return self._utf8(base64.b64decode(padded, altchars=b"-_", validate=True))
        except (binascii.Error, ValueError):
            return None

    def _base32(self, value: str) -> str | None:
        compact = "".join(value.split())
        if len(compact) < 8 or not _BASE32_PATTERN.fullmatch(compact):
            return None
        padded = compact + "=" * (-len(compact) % 8)
        try:
            return self._utf8(base64.b32decode(padded, casefold=True))
        except (binascii.Error, ValueError):
            return None

    def _base85(self, value: str) -> str | None:
        if len(value) < 5 or not _BASE85_PATTERN.fullmatch(value):
            return None
        try:
            return self._utf8(base64.b85decode(value))
        except (binascii.Error, ValueError):
            return None

    def _ascii85(self, value: str) -> str | None:
        if len(value) < 5 or not _ASCII85_PATTERN.fullmatch(value):
            return None
        adobe = value.startswith("<~") and value.endswith("~>")
        try:
            return self._utf8(base64.a85decode(value, adobe=adobe))
        except (binascii.Error, ValueError):
            return None

    def _hex(self, value: str) -> str | None:
        compact = "".join(value.split())
        if len(compact) < 4 or len(compact) % 2 or not _HEX_PATTERN.fullmatch(value):
            return None
        try:
            return self._utf8(bytes.fromhex(compact))
        except ValueError:
            return None

    def _binary(self, value: str) -> str | None:
        compact = "".join(value.split())
        if not _BINARY_PATTERN.fullmatch(value) or len(compact) % 8:
            return None
        return self._utf8(bytes(int(compact[index : index + 8], 2) for index in range(0, len(compact), 8)))

    def _octal(self, value: str) -> str | None:
        if not _OCTAL_PATTERN.fullmatch(value):
            return None
        values = [int(item, 8) for item in value.split()]
        if any(item > 255 for item in values):
            return None
        return self._utf8(bytes(values))

    def _decimal(self, value: str) -> str | None:
        if not _DECIMAL_PATTERN.fullmatch(value):
            return None
        values = [int(item) for item in re.split(r"\s*[, ]\s*", value)]
        if any(item > 255 for item in values):
            return None
        return self._utf8(bytes(values))
