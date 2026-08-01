# SPEC-025: Knowledge Retriever Foundation

## 目的

Project AegisへRAG（検索拡張生成）用の知識検索層を追加する。

## 概要

CTF問題に関連する知識をローカルから検索するための基盤クラス `KnowledgeRetriever` を作成する。

## 責務

- `KnowledgeRetriever` の提供
- `category` および `query` を入力として受け取る
- 関連知識テキストのリスト（`list[str]`）を返却する（現段階では空のリスト `[]` を返却）

## 入力

- `category`: str
- `query`: str

## 出力

- list[str] (現段階では空リスト)

## 今回実装しないもの（YAGNI）

- Embedding
- Vector Database
- FAISS
- Chroma
- Pinecone
- OpenAI Embeddings API
- Gemini Embeddings
- Web検索
- Writeupダウンロード
- HTML解析
- PDF解析
- 自動インデックス
- DB
- キャッシュ
- Controller統合
- PromptManager統合
- Judge統合
