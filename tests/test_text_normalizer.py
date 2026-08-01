from app.knowledge.text_normalizer import TextNormalizer


def test_normalize_basic_cases():
    normalizer = TextNormalizer()

    # 1. 大文字→小文字
    assert normalizer.normalize("RSA") == ["rsa"]

    # 2. カンマ除去
    assert normalizer.normalize("RSA,") == ["rsa"]

    # 3. ピリオド除去
    assert normalizer.normalize("RSA.") == ["rsa"]

    # 4. ハイフン分割
    assert normalizer.normalize("AES-CBC") == ["aes", "cbc"]

    # 5. アンダースコア分割
    assert normalizer.normalize("SQL_injection") == ["sql", "injection"]

    # 6. 括弧除去
    assert normalizer.normalize("(RSA) [AES] {CBC}") == ["rsa", "aes", "cbc"]

    # 7. 空文字→[]
    assert normalizer.normalize("") == []

    # 8. 空白のみ→[]
    assert normalizer.normalize("   \t \n ") == []

    # 9. 複数記号混在
    assert normalizer.normalize("RSA, AES-CBC SQL_injection!") == [
        "rsa",
        "aes",
        "cbc",
        "sql",
        "injection",
    ]
