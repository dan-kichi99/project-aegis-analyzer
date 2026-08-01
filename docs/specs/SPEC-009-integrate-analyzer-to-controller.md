# SPEC-009: Integrate Analyzer into Controller

## 目的

AnalyzerをControllerへ統合し、入力テキストからカテゴリ判定を行えるようにする。

## 責務

- AnalyzerをDI（依存注入）する。
- process()内でAnalyzerを呼び出し、categoryを取得する。
- 既存のAI生成フロー（PromptManager, OpenAIClient）は変更しない。

## 処理フロー

1. `Controller.process(question)` 呼び出し
2. `Analyzer.analyze(question)` を実行し、`category` を取得
3. `PromptManager.build(question)` の実行
4. `OpenAIClient.generate(prompt)` の実行
5. 応答テキストの返却

## 依存コンポーネント

- `BaseAIClient` (`app.ai.base.BaseAIClient`)
- `PromptManager` (`app.prompt.prompt_manager.PromptManager`)
- `Analyzer` (`app.analyzer.analyzer.Analyzer`)

## 今回実装しないもの（YAGNI）

- カテゴリ別AI分岐
- カテゴリ別Prompt生成（TASK-010で対応）
- Judge AI
- Analyzerの複数実行

※ 取得した `category` はTASK-010でのプロンプト分岐に使用予定のため、現時点では未使用となります。
