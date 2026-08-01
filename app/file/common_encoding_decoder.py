import base64
import binascii
import string

_MIN_ENCODED_LENGTH = 8
_BASE64_CHARACTERS = frozenset(
    string.ascii_letters + string.digits + "+/="
)
_HEX_CHARACTERS = frozenset(string.hexdigits)
_MIN_READABLE_RATIO = 0.8


def decode_common_encoding(value: str) -> str | None:
    """厳格なBase64または16進数をUTF-8文字列へ1段階デコードする。"""
    candidate = value.strip()
    if len(candidate) < _MIN_ENCODED_LENGTH:
        return None

    decoded_bytes = _decode_hex(candidate)
    if decoded_bytes is None:
        decoded_bytes = _decode_base64(candidate)
    if decoded_bytes is None:
        return None

    try:
        decoded = decoded_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None

    if not decoded or decoded == candidate:
        return None

    readable_count = sum(
        character.isprintable() or character in "\r\n\t"
        for character in decoded
    )
    if readable_count / len(decoded) < _MIN_READABLE_RATIO:
        return None

    return decoded


def _decode_hex(candidate: str) -> bytes | None:
    if (
        len(candidate) % 2 != 0
        or not all(character in _HEX_CHARACTERS for character in candidate)
    ):
        return None

    try:
        return bytes.fromhex(candidate)
    except ValueError:
        return None


def _decode_base64(candidate: str) -> bytes | None:
    if (
        len(candidate) % 4 != 0
        or not all(
            character in _BASE64_CHARACTERS
            for character in candidate
        )
    ):
        return None

    try:
        return base64.b64decode(candidate, validate=True)
    except (binascii.Error, ValueError):
        return None
