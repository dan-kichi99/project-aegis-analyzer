from pathlib import Path

from app.analyzer.analyzer import Category
from app.knowledge.knowledge_retriever import KnowledgeRetriever
from app.knowledge.retriever_evaluator import RetrieverEvaluator

BENCHMARK_CASES: list[tuple[str, str, str]] = [
    # Crypto (2 cases)
    (
        Category.CRYPTO,
        "RSA factorization attack",
        "prime factorization",
    ),
    (
        Category.CRYPTO,
        "AES CBC padding oracle",
        "cipher block chaining",
    ),
    # Web (2 cases)
    (
        Category.WEB,
        "SQL login bypass attack",
        "SQL injection vulnerability",
    ),
    (
        Category.WEB,
        "Server Side Template Injection SSTI",
        "template engine execution",
    ),
    # Rev (2 cases)
    (
        Category.REV,
        "extract hardcoded secret strings binary",
        "ASCII string extraction",
    ),
    (
        Category.REV,
        "Ghidra decompiler function analysis",
        "reverse engineering framework",
    ),
    # Misc (2 cases)
    (
        Category.MISC,
        "Base64 encoding decode scheme",
        "binary to text encoding",
    ),
    (
        Category.MISC,
        "LSB steganography image analysis",
        "least significant bit hidden data",
    ),
]


def test_retrieval_benchmark_cases_count():
    assert len(BENCHMARK_CASES) == 8


def test_retrieval_benchmark_hit_rate():
    benchmark_dir = Path("data/benchmark/knowledge")
    assert benchmark_dir.exists(), "Benchmark knowledge directory must exist"

    retriever = KnowledgeRetriever(base_dir=benchmark_dir)
    evaluator = RetrieverEvaluator(retriever)

    hit_rate = evaluator.evaluate_batch(BENCHMARK_CASES)
    assert hit_rate == 1.0
