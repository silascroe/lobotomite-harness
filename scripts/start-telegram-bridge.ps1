[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($env:LLMTESTING_TELEGRAM_BOT_TOKEN)) {
    throw 'LLMTESTING_TELEGRAM_BOT_TOKEN is not present in this PowerShell session. Run the token setup here first.'
}

$root = Split-Path -Parent $PSScriptRoot
$python = 'C:\Users\ringd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = 'python'
}

$bridge = Join-Path $PSScriptRoot 'telegram_bridge.py'
if (-not (Test-Path -LiteralPath $bridge)) {
    throw "Telegram bridge was not found at $bridge"
}

Write-Output 'Starting the Telegram bridge. Keep this window open; press Ctrl+C to stop it.'
& $python $bridge
exit $LASTEXITCODE

