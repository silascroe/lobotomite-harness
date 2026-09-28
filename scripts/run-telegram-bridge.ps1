[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$secretPath = Join-Path $root 'agent-lab\.secrets\telegram-bot-token.dpapi'
$logDir = Join-Path $root 'agent-lab\telegram-bridge-logs'
$logPath = Join-Path $logDir 'bridge.log'
$bridge = Join-Path $PSScriptRoot 'telegram_bridge.py'
$python = 'C:\Users\ringd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = 'python'
}

$exitCode = 1
$secureToken = $null
$tokenPointer = [IntPtr]::Zero
$plainToken = $null

New-Item -ItemType Directory -Path $logDir -Force | Out-Null

try {
    if (-not (Test-Path -LiteralPath $secretPath)) {
        throw "Encrypted Telegram token not found at $secretPath. Run .\scripts\install-telegram-bridge.ps1 once."
    }
    if (-not (Test-Path -LiteralPath $bridge)) {
        throw "Telegram bridge was not found at $bridge"
    }

    $encryptedToken = (Get-Content -LiteralPath $secretPath -Raw).Trim()
    if ([string]::IsNullOrWhiteSpace($encryptedToken)) {
        throw "Encrypted Telegram token file is empty: $secretPath"
    }

    $secureToken = ConvertTo-SecureString -String $encryptedToken
    $tokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
    $plainToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPointer)
    if ([string]::IsNullOrWhiteSpace($plainToken)) {
        throw 'The encrypted Telegram token decrypted to an empty value.'
    }

    $env:LLMTESTING_TELEGRAM_BOT_TOKEN = $plainToken
    $env:PYTHONUNBUFFERED = '1'

    Push-Location $root
    try {
        & $python $bridge *>> $logPath
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}
catch {
    $line = "{0} runner error: {1}" -f (Get-Date -Format o), $_.Exception.Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
    $exitCode = 1
}
finally {
    if ($tokenPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPointer)
    }
    $plainToken = $null
    $secureToken = $null
    Remove-Item Env:LLMTESTING_TELEGRAM_BOT_TOKEN -ErrorAction SilentlyContinue
}

exit $exitCode

