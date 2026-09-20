[CmdletBinding()]
param(
    [string]$TaskFile = 'agent-lab/tasks/001-static-page.md',
    [string]$RunId,
    [string]$Config = 'agent-lab/harness/config.json',
    [string]$Template,
    [string]$ProjectDir
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$python = 'C:\Users\ringd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = 'python'
}

$arguments = @(
    (Join-Path $root 'agent-lab\harness\agent_harness.py'),
    '--task-file', $TaskFile,
    '--config', $Config
)
if ($RunId) {
    $arguments += @('--run-id', $RunId)
}
if ($Template) {
    $arguments += @('--template', $Template)
}
if ($ProjectDir) {
    $arguments += @('--project-dir', $ProjectDir)
}

& $python @arguments
exit $LASTEXITCODE
