from pathlib import Path

from app.analyzer.analyzer import Category
from app.knowledge.knowledge_retriever import KnowledgeRetriever
from app.knowledge.retrieval_benchmark_runner import RetrievalBenchmarkRunner
from app.knowledge.retriever_evaluator import RetrieverEvaluator

REAL_KNOWLEDGE_CASES: list[tuple[str, str, str]] = [
    # Crypto (4件)
    (
        Category.CRYPTO,
        "RSA primes close Fermat factorization",
        "Fermat factorization",
    ),
    (
        Category.CRYPTO,
        "same modulus different exponents RSA coprime",
        "common modulus",
    ),
    (
        Category.CRYPTO,
        "AES CBC padding oracle attack error response",
        "Padding Oracle Attack",
    ),
    (
        Category.CRYPTO,
        "XOR key length Hamming distance single byte",
        "Repeated-key XOR",
    ),
    # Web (4件)
    (
        Category.WEB,
        "SQL injection UNION SELECT blind boolean error",
        "SQL injection",
    ),
    (
        Category.WEB,
        "template injection Jinja2 subclasses RCE",
        "Server Side Template Injection",
    ),
    (
        Category.WEB,
        "XSS script execution reflected stored DOM cookie",
        "Cross-Site Scripting",
    ),
    (
        Category.WEB,
        "JWT algorithm none HS256 RS256 kid header",
        "JSON Web Token",
    ),
    # Rev (4件)
    (
        Category.REV,
        "extract printable characters binary UPX password",
        "strings command",
    ),
    (
        Category.REV,
        "Ghidra decompiler pseudocode symbol tree Xrefs",
        "Ghidra",
    ),
    (
        Category.REV,
        "debug binary breakpoints registers RAX RIP GDB",
        "GNU Debugger",
    ),
    (
        Category.REV,
        "binary compares password string strcmp memory",
        "strcmp",
    ),
    # Misc (4件)
    (
        Category.MISC,
        "hidden image least significant bit zsteg steghide",
        "Steganography",
    ),
    (
        Category.MISC,
        "exiftool metadata comment GPS coordinates camera",
        "EXIF",
    ),
    (
        Category.MISC,
        "pcap wireshark network packet analysis follow stream",
        "Packet Capture",
    ),
    (
        Category.MISC,
        "magic bytes file signature header PNG JPEG hex",
        "File signatures",
    ),
]


def test_real_knowledge_dataset_count():
    data_dir = Path("data/knowledge")
    assert data_dir.exists(), "data/knowledge directory must exist"

    crypto_files = list((data_dir / "crypto").glob("*.txt"))
    web_files = list((data_dir / "web").glob("*.txt"))
    rev_files = list((data_dir / "rev").glob("*.txt"))
    misc_files = list((data_dir / "misc").glob("*.txt"))

    assert len(crypto_files) >= 5, f"Crypto files count: {len(crypto_files)}"
    assert len(web_files) >= 5, f"Web files count: {len(web_files)}"
    assert len(rev_files) >= 5, f"Rev files count: {len(rev_files)}"
    assert len(misc_files) >= 5, f"Misc files count: {len(misc_files)}"

    total_files = len(crypto_files) + len(web_files) + len(rev_files) + len(misc_files)
    assert total_files >= 20, f"Total knowledge files count: {total_files}"


def test_real_knowledge_dataset_eval():
    data_dir = Path("data/knowledge")
    retriever = KnowledgeRetriever(base_dir=data_dir)
    evaluator = RetrieverEvaluator(retriever)
    runner = RetrievalBenchmarkRunner(evaluator)

    result = runner.run(REAL_KNOWLEDGE_CASES)

    crypto_cases = [c for c in REAL_KNOWLEDGE_CASES if c[0] == Category.CRYPTO]
    web_cases = [c for c in REAL_KNOWLEDGE_CASES if c[0] == Category.WEB]
    rev_cases = [c for c in REAL_KNOWLEDGE_CASES if c[0] == Category.REV]
    misc_cases = [c for c in REAL_KNOWLEDGE_CASES if c[0] == Category.MISC]

    assert len(crypto_cases) >= 4
    assert len(web_cases) >= 4
    assert len(rev_cases) >= 4
    assert len(misc_cases) >= 4

    assert result.total >= 16
    assert result.hit_rate >= 0.875, f"Actual Hit Rate: {result.hit_rate * 100:.2f}%"
