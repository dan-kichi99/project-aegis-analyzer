$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    Write-Error "仮想環境のPythonが見つかりません。READMEのセットアップ手順を確認してください。"
    exit 1
}

Push-Location -LiteralPath $Root
try {
    & $Python -m app.main @args
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
