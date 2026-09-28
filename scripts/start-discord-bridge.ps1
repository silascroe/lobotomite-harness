[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$bridge = Join-Path $PSScriptRoot 'discord_bridge.mjs'
$nodePath = $null
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCommand) {
    $nodePath = $nodeCommand.Source
}

# Codex's bundled Node runtime is available to the agent shell but may not be
# on the user's ordinary PowerShell PATH. Prefer PATH, then use the known
# per-user runtime location as a fallback.
$bundledNode = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
if ([string]::IsNullOrWhiteSpace($nodePath) -and (Test-Path -LiteralPath $bundledNode)) {
    $nodePath = $bundledNode
}

if ([string]::IsNullOrWhiteSpace($nodePath)) {
    throw 'Node.js 22 or newer was not found on PATH or at the bundled runtime location.'
}
if (-not (Test-Path -LiteralPath $bridge)) {
    throw "Discord bridge was not found at $bridge"
}

$tokenPointer = [IntPtr]::Zero
$secureToken = $null
$plainToken = $null
$exitCode = 1

try {
    if ([string]::IsNullOrWhiteSpace($env:LLMTESTING_DISCORD_BOT_TOKEN)) {
        $secureToken = Read-Host -Prompt 'Paste the Discord bot token (input is hidden)' -AsSecureString
        $tokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
        $plainToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPointer)
        if ([string]::IsNullOrWhiteSpace($plainToken)) {
            throw 'The Discord bot token was empty.'
        }
        $env:LLMTESTING_DISCORD_BOT_TOKEN = $plainToken
    }

    $env:NODE_NO_WARNINGS = '1'
    Push-Location $root
    try {
        & $nodePath $bridge
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($tokenPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPointer)
    }
    $plainToken = $null
    $secureToken = $null
    Remove-Item Env:LLMTESTING_DISCORD_BOT_TOKEN -ErrorAction SilentlyContinue
    Remove-Item Env:NODE_NO_WARNINGS -ErrorAction SilentlyContinue
}

exit $exitCode

