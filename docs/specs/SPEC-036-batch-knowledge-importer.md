# SPEC-036: Batch Local Knowledge Importer

## 目的

指定したローカルディレクトリ内の複数 `.txt` ファイルを一括で `Knowledge`（`data/knowledge/`）へ取り込む機能を提供する。
大会前に大量の CTF Writeup・学習メモ・解法資料を効率よく投入することを目的とする。

## 構造・責務

`KnowledgeImporter` を DI（依存性注入）で受け取り、単一ファイルの取り込み処理（カテゴリ検証・拡張子確認・UTF-8読み込み・重複チェック等）はすべて `KnowledgeImporter.import_file()` へ委譲する。

`BatchKnowledgeImporter` の責務:
1. ディレクトリの存在・種別確認
2. 指定ディレクトリ直下の `.txt`（大文字小文字無視）ファイルの抽出およびファイル名昇順ソート
3. `KnowledgeImporter.import_file()` の順次呼び出し
4. 成功・失敗結果（エラー発生ファイルと例外）の集計・返却

## 仕様 (`BatchKnowledgeImporter`)

### コンストラクタ
```python
def __init__(
    self,
    knowledge_importer: KnowledgeImporter,
) -> None:
    self._knowledge_importer = knowledge_importer
import_directory()Pythondef import_directory(
    self,
    category: str,
    source_dir: Path | str,
) -> tuple[list[Path], list[tuple[Path, Exception]]]:
入力:category: str: 保存先カテゴリ（crypto, web, rev, misc）source_dir: Path | str: ソースファイルが存在するディレクトリパス出力: tuple[list[Path], list[tuple[Path, Exception]]]imported_files: 正常に取り込まれた保存先 Path のリストfailed_files: 失敗した (元ファイルPath, 発生Exception) のリスト処理詳細ディレクトリ事前検証:source_dir が存在しない場合 $\rightarrow$ FileNotFoundError を raise する。source_dir がファイルパスである場合 $\rightarrow$ ValueError を raise する。対象ファイルの抽出:source_dir 直下のファイルのみを対象とする（サブディレクトリの探索は行わない）。拡張子判定は file_path.suffix.lower() == ".txt" で行う（.txt, .TXT, .Txt 等すべて対応）。処理順の安定化:対象ファイルをファイル名（file_path.name）で昇順ソートする。一括処理とエラーハンドリング:各ファイルについて self._knowledge_importer.import_file(category, file_path) を呼び出す。個別ファイル処理中に Exception が発生した場合、処理を中断せず捕捉し、failed_files に追加して次ファイルの処理へ進む。空ディレクトリ処理:対象 .txt ファイルが 0 件の場合は ([], []) を返却する。今回実装しないもの（YAGNI）再帰ディレクトリ探索（rglob 等）ZIP / Markdown / PDF / HTML 等の形式対応Web scraping / GitHub / CTFtime 連携AI カテゴリ分類 / 要約 / 自動タグ生成 / 重複ハッシュ判定並列処理（asyncio, マルチスレッド）/ GUI / CLI / 進捗バー / データベース連携
---

## 2. `app/knowledge/batch_knowledge_importer.py`

```python
from pathlib import Path

from app.knowledge.knowledge_importer import KnowledgeImporter


class BatchKnowledgeImporter:
    """ディレクトリ内の複数ナレッジファイルを一括取り込みするクラス。"""

    def __init__(
        self,
        knowledge_importer: KnowledgeImporter,
    ) -> None:
        self._knowledge_importer = knowledge_importer

    def import_directory(
        self,
        category: str,
        source_dir: Path | str,
    ) -> tuple[list[Path], list[tuple[Path, Exception]]]:
        """指定ディレクトリ直下の.txtファイルを一括でKnowledgeへ取り込む。"""
        src_dir = Path(source_dir)

        # 1. 存在確認
        if not src_dir.exists():
            raise FileNotFoundError(f"Source directory does not exist: '{src_dir}'")

        # 2. ディレクトリ確認
        if not src_dir.is_dir():
            raise ValueError(f"Source path is not a directory: '{src_dir}'")

        # 3. 直下のファイルのみ探索 (.txt 大文字小文字無視)
        target_files: list[Path] = [
            f for f in src_dir.iterdir()
            if f.is_file() and f.suffix.lower() == ".txt"
        ]

        if not target_files:
            return ([], [])

        # 4. ファイル名でソートして安定した順序を保証
        target_files.sort(key=lambda f: f.name)

        imported_files: list[Path] = []
        failed_files: list[tuple[Path, Exception]] = []

        # 5. KnowledgeImporter.import_file() を順次呼び出し
        for file_path in target_files:
            try:
                saved_path = self._knowledge_importer.import_file(
                    category=category,
                    source_path=file_path,
                )
                imported_files.append(saved_path)
            except Exception as e:
                failed_files.append((file_path, e))

        return (imported_files, failed_files)
