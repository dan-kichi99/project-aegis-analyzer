# SPEC-035: Local Knowledge Importer Foundation

## 目的

大会前に大量の CTF Writeup・学習メモ・解法資料を Project Aegis のローカル Knowledge（`data/knowledge/`）へ安全に取り込むための簡易インポーター `KnowledgeImporter` を提供する。

## 責務

- 文字列コンテンツまたは既存のローカル `.txt` ファイルを読み込み、指定カテゴリフォルダへ `.txt` ファイルとして保存・コピーする。
- カテゴリの検証（`Category.UNKNOWN` および未定義カテゴリの排除）。
- ファイル拡張子の検証（`.txt` 限定）。
- ディレクトリトラバーサル（Path Traversal）攻撃の遮断。
- ファイルの空内容チェックおよび既存ファイルの上書き禁止。

## 仕様 (`KnowledgeImporter`)

### コンストラクタ
```python
def __init__(
    self,
    base_dir: Path | str = "data/knowledge",
) -> None:
    self._base_dir = Path(base_dir)
保存先ディレクトリ対応表 (_CATEGORY_DIR_MAP)Category.CRYPTO ("crypto") $\rightarrow$ {base_dir}/crypto/Category.WEB ("web") $\rightarrow$ {base_dir}/web/Category.REV ("rev") $\rightarrow$ {base_dir}/rev/Category.MISC ("misc") $\rightarrow$ {base_dir}/misc/Category.UNKNOWN および上記以外の文字列カテゴリは保存禁止（ValueError）。import_text()Pythondef import_text(
    self,
    category: str,
    filename: str,
    content: str,
) -> Path
カテゴリの妥当性をチェックする（Category.UNKNOWN または未定義なら ValueError）。filename が .txt 拡張子（大文字小文字区別なし）であるかチェックする（違えば ValueError）。Path(filename).name != filename または ../, ..\, /, \ 等のディレクトリスパニングを検知した場合 ValueError をスローする。content.strip() が空の場合は ValueError をスローする。保存先カテゴリディレクトリが存在しない場合は自動生成する (mkdir(parents=True, exist_ok=True))。保存先に同名ファイルが既に存在する場合は FileExistsError をスローする（上書き禁止）。UTF-8 エンコーディングで加工せずそのまま書き込み、保存先の Path オブジェクトを返却する。import_file()Pythondef import_file(
    self,
    category: str,
    source_path: Path | str,
) -> Path
source_path が存在するか確認する（存在しなければ FileNotFoundError）。source_path がファイルであるか確認する（ディレクトリなら ValueError）。拡張子が .txt であるか確認する（違えば ValueError）。UTF-8 でファイルを読み込む（読み込めなければ UnicodeDecodeError）。import_text(category, source_path.name, content) を実行して書き込む。例外仕様ValueError: 未許可・UNKNOWN カテゴリ、.txt 以外の拡張子、空コンテンツ、Path Traversal 攻撃検出時FileNotFoundError: import_file() のソースファイルが存在しない場合FileExistsError: 保存先に同名ファイルが既に存在する場合UnicodeDecodeError: UTF-8 以外のエンコーディング等でファイル読込に失敗した場合今回実装しないもの（YAGNI）Web scraping / GitHub / CTFtime 等からの自動取得PDF / Markdown / HTML / ZIP / JSON / CSV 等の他フォーマット対応自動カテゴリ分類 / AI要約 / AIタグ付け / Chunking / Normalizer 処理重複ファイルハッシュ検出 / 自動リネーム / DB / Vector DB / CLI コマンド統合
---

## 2. `app/knowledge/knowledge_importer.py`

```python
from pathlib import Path

from app.analyzer.analyzer import Category

_CATEGORY_DIR_MAP: dict[str, str] = {
    Category.CRYPTO: "crypto",
    Category.WEB: "web",
    Category.REV: "rev",
    Category.MISC: "misc",
}


class KnowledgeImporter:
    """ローカルのWriteupや資料をKnowledgeディレクトリへ安全に取り込むクラス。"""

    def __init__(
        self,
        base_dir: Path | str = "data/knowledge",
    ) -> None:
        self._base_dir = Path(base_dir)

    def import_text(
        self,
        category: str,
        filename: str,
        content: str,
    ) -> Path:
        """文字列データを取り込み、指定カテゴリ配下に.txtファイルとして保存する。"""

        # 1. カテゴリの検証
        if category not in _CATEGORY_DIR_MAP:
            raise ValueError(
                f"Invalid or unsupported category: '{category}'. "
                f"Allowed categories: {list(_CATEGORY_DIR_MAP.keys())}"
            )

        # 2. ファイル名の安全策・トラバーサル防止チェック
        if Path(filename).name != filename or ".." in filename or "/" in filename or "\\" in filename:
            raise ValueError(f"Path traversal or invalid filename detected: '{filename}'")

        # 3. 拡張子チェック (.txt 限定)
        if not filename.lower().endswith(".txt"):
            raise ValueError(f"Only .txt files are allowed. Got: '{filename}'")

        # 4. コンテンツチェック
        if not content or not content.strip():
            raise ValueError("Content cannot be empty.")

        # 5. 保存先パスの決定と構築
        dir_name = _CATEGORY_DIR_MAP[category]
        target_dir = self._base_dir / dir_name
        target_dir.mkdir(parents=True, exist_ok=True)

        target_file = target_dir / filename

        # 6. 上書き禁止チェック
        if target_file.exists():
            raise FileExistsError(f"File already exists at target: '{target_file}'")

        # 7. ファイル保存 (UTF-8, 加工なし)
        target_file.write_text(content, encoding="utf-8")

        return target_file

    def import_file(
        self,
        category: str,
        source_path: Path | str,
    ) -> Path:
        """ローカルに存在する.txtファイルを読み込み、Knowledge配下へ追加する。"""
        src = Path(source_path)

        # 1. ソースファイル存在チェック
        if not src.exists():
            raise FileNotFoundError(f"Source file does not exist: '{src}'")

        # 2. ファイルであるかのチェック
        if not src.is_file():
            raise ValueError(f"Source path is not a file: '{src}'")

        # 3. 拡張子チェック (.txt 限定)
        if src.suffix.lower() != ".txt":
            raise ValueError(f"Source file must be a .txt file. Got: '{src.name}'")

        # 4. UTF-8 で読み込み
        content = src.read_text(encoding="utf-8")

        # 5. import_text の実行
        return self.import_text(
            category=category,
            filename=src.name,
            content=content,
        )
