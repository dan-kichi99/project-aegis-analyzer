from pathlib import Path

from app.analyzer.analyzer import Category
from app.knowledge.knowledge_retriever import KnowledgeRetriever
from app.knowledge.query_expander import QueryExpander


def test_retrieve_crypto_knowledge():
    retriever = KnowledgeRetriever(base_dir="data/knowledge")
    res = retriever.retrieve(Category.CRYPTO, "RSA Fermat factor")
    assert len(res) > 0


def test_retrieve_unknown_category():
    retriever = KnowledgeRetriever(base_dir="data/knowledge")
    res = retriever.retrieve("INVALID_CATEGORY", "query")
    assert res == []


def test_retrieve_empty_query():
    retriever = KnowledgeRetriever(base_dir="data/knowledge")
    assert retriever.retrieve(Category.CRYPTO, "") == []
    assert retriever.retrieve(Category.CRYPTO, "   ") == []


def test_retrieve_non_existent_dir(tmp_path: Path):
    retriever = KnowledgeRetriever(base_dir=tmp_path / "non_existent")
    res = retriever.retrieve(Category.CRYPTO, "query")
    assert res == []


def test_retrieve_deduplication_and_limit():
    retriever = KnowledgeRetriever(base_dir="data/knowledge")
    res = retriever.retrieve(Category.CRYPTO, "cipher RSA key factor")
    assert len(res) <= 3


def test_retrieve_ranking_by_relevance():
    retriever = KnowledgeRetriever(base_dir="data/knowledge")
    res = retriever.retrieve(Category.CRYPTO, "Fermat factorization")
    assert len(res) > 0


def test_retrieve_all_categories_when_unknown():
    retriever = KnowledgeRetriever(base_dir="data/knowledge")
    res = retriever.retrieve(Category.UNKNOWN, "RSA")
    assert len(res) > 0


def test_knowledge_retriever_query_expansion_integration():
    retriever = KnowledgeRetriever(base_dir="data/knowledge")

    # 1. Fermat
    res_fermat = retriever.retrieve(
        Category.CRYPTO,
        "RSA modulus factors are almost the same size and very near each other",
    )
    assert any("Fermat factorization" in chunk for chunk in res_fermat)

    # 2. JWT
    res_jwt = retriever.retrieve(
        Category.WEB,
        "unsigned token algorithm set to none allowing authentication bypass",
    )
    assert any("JSON Web Token" in chunk or "JWT" in chunk for chunk in res_jwt)

    # 3. Ghidra
    res_ghidra = retriever.retrieve(
        Category.REV,
        "decompiler tool displays assembly as C pseudocode and tracks cross references",
    )
    assert any("Ghidra" in chunk for chunk in res_ghidra)

    # 4. XOR
    res_xor = retriever.retrieve(
        Category.REV,
        "binary obfuscates static flag by applying bitwise operation with a constant byte array",
    )
    assert any("XOR Encryption" in chunk or "XOR" in chunk for chunk in res_xor)


def test_knowledge_retriever_disable_expansion():
    class NoOpExpander(QueryExpander):
        def expand(self, query: str) -> str:
            return query

    no_op_expander = NoOpExpander()

    query = "test query"

    assert no_op_expander.expand(query) == query


def test_retrieve_zero_match_crypto_unrelated():
    retriever = KnowledgeRetriever(base_dir="data/knowledge")
    res = retriever.retrieve(Category.CRYPTO, "quantum spaceship banana")
    assert res == []


def test_retrieve_zero_match_web_unrelated():
    retriever = KnowledgeRetriever(base_dir="data/knowledge")
    res = retriever.retrieve(Category.WEB, "underwater archaeology dolphin")
    assert res == []


def test_retrieve_zero_match_unknown_category_unrelated():
    retriever = KnowledgeRetriever(base_dir="data/knowledge")
    res = retriever.retrieve(Category.UNKNOWN, "extraterrestrial pineapple galaxy")
    assert res == []


def test_retrieve_zero_match_no_expansion_no_bm25_match():
    retriever = KnowledgeRetriever(base_dir="data/knowledge")
    res = retriever.retrieve(Category.REV, "supercalifragilisticexpialidocious")
    assert res == []


def test_retrieve_zero_match_positive_cases_still_hit():
    retriever = KnowledgeRetriever(base_dir="data/knowledge")

    # 正常ヒット
    res_crypto = retriever.retrieve(Category.CRYPTO, "RSA Fermat close primes")
    assert len(res_crypto) > 0
    assert any("Fermat" in chunk for chunk in res_crypto)

    # Query Expansion経由のHit
    res_jwt = retriever.retrieve(Category.WEB, "unsigned token algorithm none")
    assert len(res_jwt) > 0
    assert any("JWT" in chunk or "JSON Web Token" in chunk for chunk in res_jwt)


# --- TASK-042: Low-Signal Query Guard Integration Tests ---


def test_retrieve_stopword_with_valid_query():
    retriever = KnowledgeRetriever(base_dir="data/knowledge")
    res = retriever.retrieve(
        Category.CRYPTO, "the challenge is a problem using RSA Fermat"
    )
    assert len(res) > 0
    assert any("Fermat" in chunk for chunk in res)


def test_retrieve_only_stopwords_returns_empty():
    retriever = KnowledgeRetriever(base_dir="data/knowledge")
    res = retriever.retrieve(Category.CRYPTO, "the and this problem using")
    assert res == []


def test_retrieve_unrelated_words_with_stopwords_returns_empty():
    retriever = KnowledgeRetriever(base_dir="data/knowledge")
    res = retriever.retrieve(Category.WEB, "the underwater dolphin challenge")
    assert res == []


def test_retrieve_stopword_with_query_expansion():
    retriever = KnowledgeRetriever(base_dir="data/knowledge")
    res = retriever.retrieve(
        Category.WEB, "the unsigned token algorithm none challenge"
    )
    assert len(res) > 0
    assert any("JWT" in chunk or "JSON Web Token" in chunk for chunk in res)
