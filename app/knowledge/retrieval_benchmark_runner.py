from dataclasses import dataclass

from app.knowledge.retriever_evaluator import RetrieverEvaluator


@dataclass(slots=True)
class BenchmarkResult:
    """ベンチマーク評価の集計結果を保持するデータクラス。"""

    total: int
    hits: int
    misses: int
    hit_rate: float


class RetrievalBenchmarkRunner:
    """ベンチマークテストケースを実行・集計するランナークラス。"""

    def __init__(
        self,
        evaluator: RetrieverEvaluator,
    ) -> None:
        self._evaluator = evaluator

    def run(
        self,
        cases: list[tuple[str, str, str]],
    ) -> BenchmarkResult:
        """指定された評価ケースを実行し、集計結果を返却する。"""
        if not cases:
            return BenchmarkResult(
                total=0,
                hits=0,
                misses=0,
                hit_rate=0.0,
            )

        hits = 0
        misses = 0

        for category, query, expected_text in cases:
            if self._evaluator.evaluate(
                category,
                query,
                expected_text,
            ):
                hits += 1
            else:
                misses += 1

        total = len(cases)

        return BenchmarkResult(
            total=total,
            hits=hits,
            misses=misses,
            hit_rate=hits / total,
        )

    def format_result(
        self,
        result: BenchmarkResult,
    ) -> str:
        """BenchmarkResultを表示用テキストへ整形する。"""
        hit_rate_pct = result.hit_rate * 100

        return (
            "Retrieval Benchmark\n"
            f"Total: {result.total}\n"
            f"Hits: {result.hits}\n"
            f"Misses: {result.misses}\n"
            f"Hit Rate: {hit_rate_pct:.2f}%"
        )
