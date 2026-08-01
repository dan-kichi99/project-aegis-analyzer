from pathlib import Path

import pytest

from app.analyzer.analyzer import Category
from app.knowledge.knowledge_retriever import KnowledgeRetriever
from app.knowledge.retriever_evaluator import RetrieverEvaluator


@pytest.fixture
def eval_knowledge_dir(tmp_path: Path) -> Path:
    """評価テスト用のナレッジディレクトリフィクスチャ"""
    crypto_dir = tmp_path / "crypto"
    web_dir = tmp_path / "web"
    crypto_dir.mkdir(parents=True)
    web_dir.mkdir(parents=True)

    (crypto_dir / "rsa.txt").write_text(
        "RSA algorithm uses prime factorization.", encoding="utf-8"
    )
    (crypto_dir / "aes.txt").write_text(
        "AES symmetric encryption with CBC mode.", encoding="utf-8"
    )
    (web_dir / "sqli.txt").write_text(
        "SQL injection in login form.", encoding="utf-8"
    )

    return tmp_path


def test_evaluate_hit_success(eval_knowledge_dir: Path):
    retriever = KnowledgeRetriever(base_dir=eval_knowledge_dir)
    evaluator = RetrieverEvaluator(retriever)

    # 1. 期待テキストが検索結果に存在 -> True
    assert evaluator.evaluate(Category.CRYPTO, "RSA prime", "prime factorization") is True


def test_evaluate_hit_failure(eval_knowledge_dir: Path):
    retriever = KnowledgeRetriever(base_dir=eval_knowledge_dir)
    evaluator = RetrieverEvaluator(retriever)

    # 2. 存在しない -> False
    assert evaluator.evaluate(Category.CRYPTO, "RSA prime", "elliptic curve") is False


def test_evaluate_case_insensitive(eval_knowledge_dir: Path):
    retriever = KnowledgeRetriever(base_dir=eval_knowledge_dir)
    evaluator = RetrieverEvaluator(retriever)

    # 3. 大文字小文字違い -> True
    assert evaluator.evaluate(Category.CRYPTO, "rsa prime", "PRIME FACTORIZATION") is True


def test_evaluate_batch_rate(eval_knowledge_dir: Path):
    retriever = KnowledgeRetriever(base_dir=eval_knowledge_dir)
    evaluator = RetrieverEvaluator(retriever)

    # 4. batch 4件中3件成功 -> 0.75
    cases = [
        (Category.CRYPTO, "RSA", "prime factorization"),  # 成功 (1)
        (Category.CRYPTO, "AES", "CBC mode"),             # 成功 (2)
        (Category.WEB, "SQL", "SQL injection"),           # 成功 (3)
        (Category.CRYPTO, "RSA", "nonexistent term"),     # 失敗 (0)
    ]

    hit_rate = evaluator.evaluate_batch(cases)
    assert hit_rate == 0.75


def test_evaluate_batch_empty():
    # retrieverが空データの場合のEvaluator動作テスト
    retriever = KnowledgeRetriever(base_dir=Path("non_existent_path"))
    evaluator = RetrieverEvaluator(retriever)

    # 5. batch空 -> 0.0
    assert evaluator.evaluate_batch([]) == 0.0
