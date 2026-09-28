[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{0,50}$')]
    [string]$RunId,

    [switch]$Follow
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$eventsPath = Join-Path (Join-Path $root 'agent-lab\runs') (Join-Path $RunId 'events.jsonl')
if (-not (Test-Path -LiteralPath $eventsPath -PathType Leaf)) {
    throw "Events log not found for run '$RunId'. Start a run and copy its run ID from Agent Lab."
}
if ($Follow) {
    Write-Host "Following model responses for $RunId. Press Ctrl+C to stop."
}

Get-Content -LiteralPath $eventsPath -Encoding UTF8 -Wait:$Follow | ForEach-Object {
    try {
        $record = $_ | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        Write-Warning 'Skipped an unreadable event-log line.'
        return
    }

    if ($record.event -ne 'model_response') {
        return
    }

    $data = $record.data
    $details = @("turn $($data.turn)")
    if ($data.provider) { $details += [string]$data.provider }
    if ($data.reasoning_level) { $details += "reasoning $($data.reasoning_level)" }
    if ($data.finish_reason) { $details += "finish $($data.finish_reason)" }

    Write-Host "`n--- Model response: $($details -join ' / ') ---"
    if ($data.reasoning_content) {
        Write-Host '[Provider reasoning_content]'
        Write-Output ([string]$data.reasoning_content)
    }
    if ($data.content) {
        Write-Host '[Returned content]'
        Write-Output ([string]$data.content)
    }
}

