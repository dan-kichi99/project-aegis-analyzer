# SPEC-037: Retrieval Benchmark Runner

## 目的

TASK-032 / TASK-033 で構築した `RetrieverEvaluator` および固定ベンチマークケース（8件）の評価結果を集計・整形し、ローカル環境で定量的に確認できるようにする Runner を追加する。

検索アルゴリズム本体の改修は行わず、評価結果の集計と表示フォーマットに特化する。

## 構造と責務

- `BenchmarkResult`: 評価結果データを保持するデータ構造（`total`, `hits`, `misses`, `hit_rate`）。
- `RetrievalBenchmarkRunner`: `RetrieverEvaluator` を DI（依存性注入）で受け取り、複数テストケースの個別評価を呼び出して集計結果（`BenchmarkResult`）および整形文字列を生成する。

## 仕様

### `BenchmarkResult` (dataclass)
```python
@dataclass(slots=True)
class BenchmarkResult:
    total: int
    hits: int
    misses: int
    hit_rate: float
RetrievalBenchmarkRunner
コンストラクタ
Python
def __init__(
    self,
    evaluator: RetrieverEvaluator,
) -> None:
    self._evaluator = evaluator
run()
Python
def run(
    self,
    cases: list[tuple[str, str, str]],
) -> BenchmarkResult:
各ケース (category, query, expected_text) に対し、self._evaluator.evaluate() を順次呼び出す。

True（Hit）の件数を hits、False（Miss）の件数を misses としてカウント。

total = len(cases)、hit_rate = hits / total を算出。

cases が空の場合は BenchmarkResult(total=0, hits=0, misses=0, hit_rate=0.0) を返却する。

format_result()
Python
def format_result(
    self,
    result: BenchmarkResult,
) -> str:
BenchmarkResult を以下形式の表示用文字列へフォーマットする（print() などの出力処理は含めない）。

Plaintext
Retrieval Benchmark
Total: 8
Hits: 8
Misses: 0
Hit Rate: 100.00%
今回実装しないもの（YAGNI）
CSV / JSON / DB / ログ保存 / グラフ描画

CLI / GUI インターフェース / 自動比較 / 過去履歴保存

実行時間計測 / API 料金計測

Precision / Recall / F1 / MRR / NDCG / MAP 等の高度指標

外部 API 通信


---

## 2. `app/knowledge/retrieval_benchmark_runner.py`

```python
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
            if self._evaluator.evaluate(category, query, expected_text):
                hits += 1
            else:
                misses += 1

        total = len(cases)
        hit_rate = hits / total

        return BenchmarkResult(
            total=total,
            hits=hits,
            misses=misses,
            hit_rate=hit_rate,
        )

    def format_result(
        self,
        result: BenchmarkResult,
    ) -> str:
        """BenchmarkResultを表示用のテキスト文字列へ整形する。"""
        hit_rate_pct = result.hit_rate * 100
        return (
            "Retrieval Benchmark\n"
            f"Total: {result.total}\n"
            f"Hits: {result.hits}\n"
            f"Misses: {result.misses}\n"
            f"Hit Rate: {hit_rate_pct:.2f}%"
        )
