# SPEC-033: Retrieval Benchmark Dataset

## 目的

`KnowledgeRetriever` の検索品質を継続的に計測・検証するための小規模固定ベンチマークデータセットおよび評価テストを追加する。

今後、検索アルゴリズム、Chunking、Tokenizer、重複除去ロジック等を変更・改善した際に、同一のデータセットと問題ケースを用いて「検索精度が向上したか」「デグレーションが発生していないか」を定量的に比較可能にする。

## ベンチマーク構成

`data/benchmark/knowledge/` 配下にカテゴリ別のダミーナレッジファイル（.txt）を配置する。

- `data/benchmark/knowledge/crypto/`
  - `rsa.txt`
  - `aes.txt`
- `data/benchmark/knowledge/web/`
  - `sql_injection.txt`
  - `ssti.txt`
- `data/benchmark/knowledge/rev/`
  - `strings.txt`
  - `ghidra.txt`
- `data/benchmark/knowledge/misc/`
  - `base64.txt`
  - `steganography.txt`

## カテゴリ構成・ケース数

計 8 ケース（各カテゴリ 2 ケース）

- **Crypto**: 2ケース
- **Web**: 2ケース
- **Rev**: 2ケース
- **Misc**: 2ケース

## 評価方法

1. `KnowledgeRetriever` の `base_dir` に `"data/benchmark/knowledge"` を指定してインスタンス化する。
2. `RetrieverEvaluator` に生成した `KnowledgeRetriever` を注入する。
3. `BENCHMARK_CASES`（計 8 件の `(category, query, expected_text)`）を `RetrieverEvaluator.evaluate_batch()` で実行し、Hit Rate を計測する。

## 現在の Baseline

- **ヒット数**: 8 / 8 Hit
- **Hit Rate**: 1.0 (100%)

## 変更禁止対象

- `app/knowledge/knowledge_retriever.py`
- `app/knowledge/retriever_evaluator.py`
- `app/knowledge/text_chunker.py`
- `app/knowledge/text_normalizer.py`
- `app/knowledge/duplicate_chunk_filter.py`
- `Controller` / `PromptManager` / `Judge` / `main.py` / `requirements.txt`

## 今回実装しないもの（YAGNI）

- 大規模データセット / 外部CTFデータセットの自動ダウンロード
- CSV / JSON / DB 永続化機能
- AIによる評価データ生成
- Precision / Recall / F1 / MRR / NDCG / MAP 等の高度指標
- 実行時間・API料金ベンチマーク
- 自動パラメータチューニング
