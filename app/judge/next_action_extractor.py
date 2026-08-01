from typing import ClassVar

from app.analyzer.analyzer import Category


class NextActionExtractor:
    """AI回答およびカテゴリから次に試すアクション(next_actions)を抽出・生成するクラス"""

    _ACTIONS_MAP: ClassVar[dict[str, list[str]]] = {
        Category.CRYPTO: [
            "エンコード・暗号方式を再確認する",
            "与えられた鍵・nonce・IV・パラメータを整理する",
            "既知のCTF暗号パターンと照合する",
        ],
        Category.WEB: [
            "入力箇所とレスポンス差分を確認する",
            "認証・Cookie・Session・JWT周辺を確認する",
            "テンプレート・DB・ファイル処理の挙動を確認する",
        ],
        Category.REV: [
            "strings等で埋め込み文字列を確認する",
            "main関数と比較処理を重点的に確認する",
            "逆アセンブル結果と入力検証ロジックを追う",
        ],
        Category.MISC: [
            "file形式とメタデータを確認する",
            "埋め込みファイルや追加データの有無を確認する",
            "通信・画像・音声などカテゴリ固有情報を再確認する",
        ],
        Category.UNKNOWN: [
            "問題文・添付ファイル・ソースコードなど追加情報を確認する",
            "問題カテゴリを再判定する",
        ],
    }

    def extract(
        self,
        category: str,
        response: str,
    ) -> list[str]:
        """
        カテゴリおよびAIの応答を受け取り、カテゴリに応じた次のアクションのリストを返却する。
        """
        return self._ACTIONS_MAP.get(
            category,
            self._ACTIONS_MAP[Category.UNKNOWN],
        )