[CmdletBinding()]
param(
    [int]$Port = 8080,
    [int]$Context = 8192,
    [string]$Device = 'Vulkan0'
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$bin = Join-Path $root 'runtime\llama.cpp\b11045-vulkan\bin\llama-server.exe'
$model = Join-Path $root 'models\Qwen3-8B-GGUF\Qwen3-8B-Q4_K_M.gguf'
$runtimeDir = Split-Path -Parent $bin
$log = Join-Path $runtimeDir 'llama-server.out.log'
$errorLog = Join-Path $runtimeDir 'llama-server.err.log'

if (-not (Test-Path -LiteralPath $bin)) {
    throw "llama-server.exe was not found at $bin"
}

if (-not (Test-Path -LiteralPath $model)) {
    throw "The Qwen3 model was not found at $model"
}

$healthUri = "http://127.0.0.1:$Port/health"
try {
    $health = Invoke-RestMethod -UseBasicParsing -Uri $healthUri -TimeoutSec 2
    if ($health.status -eq 'ok') {
        Write-Output "The Qwen3 server is already healthy at http://127.0.0.1:$Port."
        exit 0
    }
}
catch {
    # Nothing is listening yet; start the server below.
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
    Model = $model
    Log = $log
    ErrorLog = $errorLog
}

