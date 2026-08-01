from pathlib import Path

from app.analyzer.analyzer import Category
from app.knowledge.knowledge_retriever import KnowledgeRetriever
from app.knowledge.retrieval_benchmark_runner import RetrievalBenchmarkRunner
from app.knowledge.retriever_evaluator import RetrieverEvaluator

HARD_CASES: list[tuple[str, str, str]] = [
    # Crypto (4件)
    (
        Category.CRYPTO,
        "RSA modulus factors are almost the same size and very near each other",
        "Fermat factorization",
    ),
    (
        Category.CRYPTO,
        "two ciphertexts share identical N but different exponent values without factorization",
        "common modulus",
    ),
    (
        Category.CRYPTO,
        "decryption server leaks bad padding error response allows recovery of block secret",
        "Padding Oracle Attack",
    ),
    (
        Category.CRYPTO,
        "cipher bytes repeat with a short secret and English plaintext frequency distribution",
        "Repeated-key XOR",
    ),
    # Web (4件)
    (
        Category.WEB,
        "Jinja expression evaluates arithmetic inside user controlled template causing remote code execution",
        "Server Side Template Injection",
    ),
    (
        Category.WEB,
        "web parameter reads /etc/passwd using dot dot slash relative path navigation",
        "Local File Inclusion",
    ),
    (
        Category.WEB,
        "database query appends malicious union payload after single quote injection test",
        "SQL injection",
    ),
    (
        Category.WEB,
        "unsigned token algorithm set to none allowing authentication bypass on web session",
        "JSON Web Token",
    ),
    # Rev (4件)
    (
        Category.REV,
        "program checks entered password against constant string during execution in memory",
        "strcmp",
    ),
    (
        Category.REV,
        "inspect registers and memory while ELF executable is running using stepi and breakpoints",
        "GNU Debugger",
    ),
    (
        Category.REV,
        "decompiler tool displays assembly as C pseudocode and tracks function cross references",
        "Ghidra",
    ),
    (
        Category.REV,
        "binary obfuscates static flag by applying bitwise operation with a constant byte array",
        "XOR Encryption",
    ),
    # Misc (4件)
    (
        Category.MISC,
        "extension says jpg but header bytes indicate another format when inspecting file magic",
        "File signatures",
    ),
    (
        Category.MISC,
        "find GPS coordinates and camera model metadata hidden inside taken photo",
        "EXIF",
    ),
    (
        Category.MISC,
        "analyze captured Wireshark network stream to find transmitted unencrypted web payload",
        "Packet Capture",
    ),
    (
        Category.MISC,
        "extract hidden payload from least significant bit of image color channels",
        "Steganography",
    ),
]


def test_hard_retrieval_benchmark_count_and_categories():
    assert len(HARD_CASES) >= 16, "HARD_CASES must have at least 16 cases"

    crypto_cases = [c for c in HARD_CASES if c[0] == Category.CRYPTO]
    web_cases = [c for c in HARD_CASES if c[0] == Category.WEB]
    rev_cases = [c for c in HARD_CASES if c[0] == Category.REV]
    misc_cases = [c for c in HARD_CASES if c[0] == Category.MISC]

    assert len(crypto_cases) >= 4, f"Crypto count: {len(crypto_cases)}"
    assert len(web_cases) >= 4, f"Web count: {len(web_cases)}"
    assert len(rev_cases) >= 4, f"Rev count: {len(rev_cases)}"
    assert len(misc_cases) >= 4, f"Misc count: {len(misc_cases)}"


def test_hard_retrieval_benchmark_execution():
    data_dir = Path("data/knowledge")
    assert data_dir.exists(), "data/knowledge directory must exist"

    retriever = KnowledgeRetriever(base_dir=data_dir)
    evaluator = RetrieverEvaluator(retriever)
    runner = RetrievalBenchmarkRunner(evaluator)

    result = runner.run(HARD_CASES)

    # Miss可視化のための個別評価ループ
    failed_details: list[str] = []
    for category, query, expected_text in HARD_CASES:
        hit = evaluator.evaluate(category, query, expected_text)
        if not hit:
            failed_details.append(
                f"FAILED -> Category: {category}, Query: '{query}', Expected: '{expected_text}'"
            )

    failure_report = "\n".join(failed_details)
    assert result.hit_rate >= 0.50, (
        f"Hit rate too low: {result.hit_rate * 100:.2f}% (Required >= 50.00%)\n"
        f"Failed Cases:\n{failure_report}"
    )
