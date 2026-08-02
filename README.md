# Project Aegis

Project Aegisは、CTF問題と添付ファイルをローカル解析し、必要な場合に専門AgentとOpenAIを利用するWindows向け解析支援アプリケーションです。Flag候補は正解確定や自動提出を意味しません。

## 対応環境

- Windows 10/11
- Python 3.11以上を推奨
- PowerShell 5.1以上
- Tkinter（GUIを使う場合のみ。通常のWindows版Pythonに同梱）

外部Tool（strings、file、exiftool、readelf、objdump、nm、binwalk）は任意です。未導入でも、利用可能なローカル解析とAI解析は使用できます。外部Toolは登録済みPolicyを経由する場合だけ実行されます。

## セットアップ

リポジトリのルートで次を実行します。

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

OpenAI機能を使う場合だけ`.env`またはプロセス環境へ`OPENAI_API_KEY`を設定してください。APIキー、Token、個人パスをGitへ追加しないでください。キーが未設定でもGUIとローカル解析は起動できますが、AI経路は利用できません。

## 起動

CLI：

```powershell
.\scripts\run_cli.ps1
# または
.\.venv\Scripts\python.exe -m app.main
```

GUI：

```powershell
.\scripts\run_gui.ps1
# または
.\.venv\Scripts\python.exe -m app.gui_main
```

環境診断（API通信や外部Tool実行は行いません）：

```powershell
.\scripts\check_environment.ps1
# または
.\.venv\Scripts\python.exe -m app.diagnostics_main
```

スクリプトは仮想環境の作成、依存インストール、ExecutionPolicy変更、PATH変更を自動では行いません。

## 安全上の注意

- 生成Pythonコードの制限付き実行は完全なサンドボックスではありません。内容と静的検査結果を確認し、明示承認した場合だけ実行してください。
- 外部Toolは読み取り中心の固定Policyと引数検証を経由します。未登録Toolは実行されません。
- Agent、Tool、コード実行出力のFlagは候補であり、正解確定や自動提出ではありません。
- キャンセルは未開始のAI通信を抑止しますが、既に開始済みの通信や処理を強制終了しません。
- 実マルウェアや信頼できない生成コードを実行しないでください。

## テスト

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests
git diff --check
```

本リポジトリはPyInstaller、exe、MSI、インストーラー、自動更新を提供していません。
