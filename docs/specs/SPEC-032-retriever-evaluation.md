# SPEC-032: Knowledge Retriever Evaluation Foundation

## 目的

`KnowledgeRetriever` の検索品質をローカルで簡易評価できる基盤を整備する。

今後行われる BM25アルゴリズム改善、Tokenizer改善、Chunking改善、重複除去（Dedup）改善などが、実際に検索精度の向上（Hit Rate改善）につながっているかを定量的かつ安全に検証可能にする。

## 責務

- `KnowledgeRetriever` の検索実行（`retrieve()` 呼び出し）
- 検索結果内に指定された `expected_text` が含まれているかの Hit 判定（大文字小文字無視）
- 複数評価ケースに対する一括評価および Hit Rate（成功率）の計算

## 仕様 (`RetrieverEvaluator`)

### コンストラクタ
`KnowledgeRetriever` を DI で受け取る。

```python
def __init__(
    self,
    retriever: KnowledgeRetriever,
) -> None:
    self._retriever = retriever
evaluate()
単一ケースに対する Hit 判定を行う。

入力:

category: str - 検索カテゴリ (crypto, web, rev, misc, unknown)

query: str - 検索クエリ

expected_text: str - 期待されるヒット文字列

出力: bool

処理内容:

self._retriever.retrieve(category, query) を実行する。

返却された各チャンク文字列内に expected_text が大文字小文字を区別せず含まれるか確認する（.lower() 比較）。

含まれていれば True、含まれていなければ False を返却する。

evaluate_batch()
複数ケースに対する Hit Rate（成功率）を計算する。

入力: cases: list[tuple[str, str, str]]

各要素は (category, query, expected_text) のタプル

出力: float（0.0 〜 1.0）

処理内容:

cases が空の場合は 0.0 を返却する。

各ケースに対して evaluate() を実行し、True の件数をカウントする。

(成功件数) / (全ケース数) を計算して返却する（例: 4件中3件成功で 0.75）。

今回実装しないもの（YAGNI）
高度な検索評価指標（Precision, Recall, F1, MRR, NDCG, MAP）

AI評価 / Semantic similarity / Embedding評価

ベンチマークデータベース / ファイル出力（CSV, JSON）/ グラフ描画 / ログ保存

外部API呼び出し / パラメータ自動チューニング


---

## 2. `app/knowledge/retriever_evaluator.py`

```python
from app.knowledge.knowledge_retriever import KnowledgeRetriever


class RetrieverEvaluator:
    """KnowledgeRetrieverの検索品質（Hit Rate）を評価するクラス。"""

    def __init__(self, retriever: KnowledgeRetriever) -> None:
        self._retriever = retriever

    def evaluate(
        self,
        category: str,
        query: str,
        expected_text: str,
    ) -> bool:
        """単一のテストケースを実行し、期待テキストが上位結果に含まれるか検証する。"""
        results = self._retriever.retrieve(category, query)
        expected_lower = expected_text.lower()

        for chunk in results:
            if expected_lower in chunk.lower():
                return True

        return False

    def evaluate_batch(
        self,
        cases: list[tuple[str, str, str]],
    ) -> float:
        """複数のテストケースを一括実行し、Hit Rate（成功率）を算出する。"""
        if not cases:
            return 0.0

        success_count = sum(
            1 for category, query, expected_text in cases
            if self.evaluate(category, query, expected_text)
        )

        return success_count / len(cases)
