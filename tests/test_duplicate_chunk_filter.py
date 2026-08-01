from app.knowledge.duplicate_chunk_filter import DuplicateChunkFilter


def test_filter_empty_list():
    filter_inst = DuplicateChunkFilter()
    assert filter_inst.filter([]) == []


def test_filter_exact_duplicates():
    filter_inst = DuplicateChunkFilter()
    chunks = [
        "RSA factorization attack using Fermat method",
        "RSA factorization attack using Fermat method",
    ]
    result = filter_inst.filter(chunks)
    assert len(result) == 1
    assert result[0] == "RSA factorization attack using Fermat method"


def test_filter_case_insensitive_duplicates():
    filter_inst = DuplicateChunkFilter()
    chunks = [
        "RSA factorization attack using Fermat method",
        "rsa factorization attack using fermat method",
    ]
    result = filter_inst.filter(chunks)
    assert len(result) == 1


def test_filter_slight_whitespace_difference():
    filter_inst = DuplicateChunkFilter()
    chunks = [
        "RSA factorization attack using Fermat method",
        "RSA  factorization   attack using Fermat method ",
    ]
    result = filter_inst.filter(chunks)
    assert len(result) == 1


def test_filter_with_punctuation_and_normalization():
    filter_inst = DuplicateChunkFilter()

    # ピリオドの有無および大文字小文字による違い
    chunks1 = [
        "RSA factorization attack using Fermat method.",
        "rsa factorization attack using fermat method",
    ]
    result1 = filter_inst.filter(chunks1)
    assert len(result1) == 1

    # ハイフン vs 空白の違い
    chunks2 = [
        "AES-CBC padding oracle",
        "aes cbc padding oracle",
    ]
    result2 = filter_inst.filter(chunks2)
    assert len(result2) == 1

    # アンダースコア vs 空白の違い
    chunks3 = [
        "SQL_injection vulnerability",
        "sql injection vulnerability",
    ]
    result3 = filter_inst.filter(chunks3)
    assert len(result3) == 1


def test_filter_different_content_kept():
    filter_inst = DuplicateChunkFilter()
    chunks = [
        "RSA factorization attack using Fermat method",
        "AES CBC padding oracle vulnerability in web application",
    ]
    result = filter_inst.filter(chunks)
    assert len(result) == 2
    assert result[0] == "RSA factorization attack using Fermat method"
    assert result[1] == "AES CBC padding oracle vulnerability in web application"


def test_filter_preserves_order_and_handles_multiple():
    filter_inst = DuplicateChunkFilter()
    chunks = [
        "First unique chunk about RSA cryptography",
        "First unique chunk about RSA cryptography.",  # ピリオド付き重複（除外）
        "Second unique chunk about AES encryption",
        "Third unique chunk about SQL injection vulnerability",
        "Second unique chunk about AES-encryption",  # ハイフン付き重複（除外）
    ]
    result = filter_inst.filter(chunks)
    assert len(result) == 3
    assert result[0] == "First unique chunk about RSA cryptography"
    assert result[1] == "Second unique chunk about AES encryption"
    assert result[2] == "Third unique chunk about SQL injection vulnerability"
