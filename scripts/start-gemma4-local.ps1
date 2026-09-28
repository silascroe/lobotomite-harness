[CmdletBinding()]
param(
    [int]$Port = 8080,
    [int]$Context = 8192,
    [string]$Device = 'Vulkan0',
    [int]$ReasoningBudget = 1024,
    [ValidateSet('E2B', 'E4B')]
    [string]$ModelSize = 'E4B'
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$bin = Join-Path $root 'runtime\llama.cpp\b11045-vulkan\bin\llama-server.exe'
$modelPaths = @{
    E2B = Join-Path $root 'models\Gemma4-E2B-GGUF\gemma-4-E2B_q4_0-it.gguf'
    E4B = Join-Path $root 'models\Gemma4-E4B-GGUF\gemma-4-E4B_q4_0-it.gguf'
}
$model = $modelPaths[$ModelSize]
$runtimeDir = Split-Path -Parent $bin
$logStem = if ($ModelSize -eq 'E4B') { 'gemma4-server' } else { "gemma4-$ModelSize-server" }
$log = Join-Path $runtimeDir "$logStem.out.log"
$errorLog = Join-Path $runtimeDir "$logStem.err.log"

if (-not (Test-Path -LiteralPath $bin)) {
    throw "llama-server.exe was not found at $bin"
}

if (-not (Test-Path -LiteralPath $model)) {
    throw "The Gemma 4 $ModelSize model was not found at $model"
}

$healthUri = "http://127.0.0.1:$Port/health"
try {
    $health = Invoke-RestMethod -UseBasicParsing -Uri $healthUri -TimeoutSec 2
    if ($health.status -eq 'ok') {
        Write-Output "A local model server is already healthy at http://127.0.0.1:$Port. Stop it before switching models."
        exit 0
    }
}
catch {
    # Nothing is listening yet; start Gemma below.
}

$arguments = @(
    '-m', $model,
    '--host', '127.0.0.1',
    '--port', "$Port",
    '-c', "$Context",
    '-np', '1',
    '-ngl', 'all',
    '--device', $Device,
    '--jinja',
    '--reasoning', 'on',
    '--reasoning-budget', "$ReasoningBudget",
    '--cors-origins', 'localhost'
)

$process = Start-Process `
    -FilePath $bin `
    -ArgumentList $arguments `
    -WorkingDirectory $runtimeDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $log `
    -RedirectStandardError $errorLog `
    -PassThru

[pscustomobject]@{
    PID = $process.Id
    Endpoint = "http://127.0.0.1:$Port"
    ModelSize = $ModelSize
    Model = $model
    Reasoning = "on (budget $ReasoningBudget tokens)"
    Log = $log
    ErrorLog = $errorLog
}

