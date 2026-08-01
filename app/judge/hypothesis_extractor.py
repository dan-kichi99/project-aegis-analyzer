from typing import ClassVar

from app.analyzer.analyzer import Category


class HypothesisExtractor:
    """AI回答およびカテゴリから仮説(hypothesis)を抽出・生成するクラス"""

    _HYPOTHESIS_MAP: ClassVar[dict[str, str]] = {
        Category.CRYPTO: "暗号方式・エンコード方式・鍵の扱いに追加の解析余地がある可能性があります。",
        Category.WEB: "入力処理・認証・セッション・テンプレート処理などに追加の確認余地がある可能性があります。",
        Category.REV: "文字列・制御フロー・比較処理・難読化部分に追加の解析余地がある可能性があります。",
        Category.MISC: "ファイル形式・メタデータ・埋め込みデータ・通信データなどに追加の確認余地がある可能性があります。",
        Category.UNKNOWN: "問題文だけではカテゴリや解法候補を十分に特定できていません。追加情報の確認が必要です。",
    }

    def extract(
        self,
        category: str,
        response: str,
    ) -> str:
        """
        カテゴリおよびAIの応答を受け取り、カテゴリに応じた仮説テキストを返却する。
        """
        return self._HYPOTHESIS_MAP.get(
            category,
            self._HYPOTHESIS_MAP[Category.UNKNOWN],
        )