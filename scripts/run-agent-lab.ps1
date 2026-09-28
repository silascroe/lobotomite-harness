[CmdletBinding()]
param(
    [string]$TaskFile = 'agent-lab/tasks/001-static-page.md',
    [string]$ResumeRun,
    [string]$RunId,
    [string]$Config = 'agent-lab/harness/config.json',
    [string]$Template,
    [string]$ProjectDir,
    [string]$SkillOverridesJson
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$python = 'C:\Users\ringd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = 'python'
}

$arguments = @((Join-Path $root 'agent-lab\harness\agent_harness.py'))
if ($ResumeRun) {
    if ($RunId -or $Template -or $ProjectDir -or $SkillOverridesJson) {
        throw '-ResumeRun cannot be combined with -RunId, -Template, -ProjectDir, or -SkillOverridesJson.'
    }
    $arguments += @('--resume-run', $ResumeRun)
} else {
    $arguments += @('--task-file', $TaskFile, '--config', $Config)
    if ($RunId) {
        $arguments += @('--run-id', $RunId)
    }
    if ($Template) {
        $arguments += @('--template', $Template)
    }
    if ($ProjectDir) {
        $arguments += @('--project-dir', $ProjectDir)
    }
    if ($SkillOverridesJson) {
        $arguments += @('--skill-overrides-json', $SkillOverridesJson)
    }
}

& $python @arguments
exit $LASTEXITCODE

