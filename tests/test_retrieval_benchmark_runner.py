from pathlib import Path

from app.analyzer.analyzer import Category
from app.knowledge.knowledge_retriever import KnowledgeRetriever
from app.knowledge.retrieval_benchmark_runner import (
    BenchmarkResult,
    RetrievalBenchmarkRunner,
)
from app.knowledge.retriever_evaluator import RetrieverEvaluator
from tests.test_retrieval_benchmark import BENCHMARK_CASES


class FakeEvaluator(RetrieverEvaluator):
    """テスト用モックEvaluator（指定インデックスのテスト判定結果をシミュレート）"""

    def __init__(self, return_values: list[bool]) -> None:
        self._return_values = return_values
        self._call_count = 0

    def evaluate(self, category: str, query: str, expected_text: str) -> bool:
        result = self._return_values[self._call_count]
        self._call_count += 1
        return result


def test_runner_run_partial_success():
    # 1. 4件中3件成功 (True, True, True, False)
    fake_evaluator = FakeEvaluator([True, True, True, False])
    runner = RetrievalBenchmarkRunner(evaluator=fake_evaluator)

    cases = [
        (Category.CRYPTO, "q1", "e1"),
        (Category.CRYPTO, "q2", "e2"),
        (Category.WEB, "q3", "e3"),
        (Category.REV, "q4", "e4"),
    ]

    result = runner.run(cases)
    assert result.total == 4
    assert result.hits == 3
    assert result.misses == 1
    assert result.hit_rate == 0.75


def test_runner_run_all_success():
    # 2. 全件成功
    fake_evaluator = FakeEvaluator([True, True])
    runner = RetrievalBenchmarkRunner(evaluator=fake_evaluator)

    cases = [
        (Category.CRYPTO, "q1", "e1"),
        (Category.WEB, "q2", "e2"),
    ]

    result = runner.run(cases)
    assert result.total == 2
    assert result.hits == 2
    assert result.misses == 0
    assert result.hit_rate == 1.0


def test_runner_run_all_failed():
    # 3. 全件失敗
    fake_evaluator = FakeEvaluator([False, False])
    runner = RetrievalBenchmarkRunner(evaluator=fake_evaluator)

    cases = [
        (Category.CRYPTO, "q1", "e1"),
        (Category.WEB, "q2", "e2"),
    ]

    result = runner.run(cases)
    assert result.total == 2
    assert result.hits == 0
    assert result.misses == 2
    assert result.hit_rate == 0.0


def test_runner_run_empty_cases():
    # 4. 空ケース
    fake_evaluator = FakeEvaluator([])
    runner = RetrievalBenchmarkRunner(evaluator=fake_evaluator)

    result = runner.run([])
    assert result.total == 0
    assert result.hits == 0
    assert result.misses == 0
    assert result.hit_rate == 0.0


def test_runner_format_result():
    # 5. format_result() 文字列検証
    fake_evaluator = FakeEvaluator([])
    runner = RetrievalBenchmarkRunner(evaluator=fake_evaluator)

    res = BenchmarkResult(total=4, hits=3, misses=1, hit_rate=0.75)
    formatted = runner.format_result(res)

    assert "Retrieval Benchmark" in formatted
    assert "Total: 4" in formatted
    assert "Hits: 3" in formatted
    assert "Misses: 1" in formatted
    assert "Hit Rate: 75.00%" in formatted


def test_runner_integration_with_benchmark_dataset():
    # 本番Benchmarkデータ（data/benchmark/knowledge）との統合テスト
    benchmark_dir = Path("data/benchmark/knowledge")
    assert benchmark_dir.exists(), "Benchmark knowledge directory must exist"

    retriever = KnowledgeRetriever(base_dir=benchmark_dir)
    evaluator = RetrieverEvaluator(retriever)
    runner = RetrievalBenchmarkRunner(evaluator=evaluator)

    result = runner.run(BENCHMARK_CASES)

    assert result.total == 8
    assert result.hits == 8
    assert result.misses == 0
    assert result.hit_rate == 1.0

    formatted = runner.format_result(result)
    assert "Total: 8" in formatted
    assert "Hits: 8" in formatted
    assert "Misses: 0" in formatted
    assert "Hit Rate: 100.00%" in formatted
