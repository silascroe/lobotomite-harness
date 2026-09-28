[CmdletBinding()]
param(
    [int]$Port = 8787
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$python = 'C:\Users\ringd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = 'python'
}

$healthUri = "http://127.0.0.1:$Port/api/health"
try {
    $health = Invoke-RestMethod -UseBasicParsing -Uri $healthUri -TimeoutSec 2
    if ($health.status -eq 'ok') {
        Write-Output "Agent Lab UI is already running at http://127.0.0.1:$Port"
        exit 0
    }
}
catch {
    # Nothing is listening yet; start the UI below.
}

$server = Join-Path $root 'agent-lab\ui\server.py'
$logDir = Join-Path $root 'agent-lab\ui'
$stdoutLog = Join-Path $logDir 'server.out.log'
$stderrLog = Join-Path $logDir 'server.err.log'
$arguments = @($server, '--port', "$Port")

$process = Start-Process `
    -FilePath $python `
    -ArgumentList $arguments `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 250
    try {
        $health = Invoke-RestMethod -UseBasicParsing -Uri $healthUri -TimeoutSec 1
        if ($health.status -eq 'ok') {
            [pscustomobject]@{
                PID = $process.Id
                URL = "http://127.0.0.1:$Port"
                Log = $stdoutLog
                ErrorLog = $stderrLog
            }
            exit 0
        }
    }
    catch {
        # Keep waiting for the server to bind.
    }
}

throw "Agent Lab UI did not become healthy. Check $stderrLog"

