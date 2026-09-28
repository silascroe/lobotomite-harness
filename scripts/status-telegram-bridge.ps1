[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$taskName = 'Agent Lab Telegram Bridge'
$logPath = Join-Path $root 'agent-lab\telegram-bridge-logs\bridge.log'

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Output "Task not installed: $taskName"
    Write-Output 'Run .\scripts\install-telegram-bridge.ps1 to install it.'
    exit 1
}

$info = Get-ScheduledTaskInfo -TaskName $taskName
[pscustomobject]@{
    TaskName = $task.TaskName
    State = $task.State
    LastRunTime = $info.LastRunTime
    NextRunTime = $info.NextRunTime
    LastTaskResult = $info.LastTaskResult
    Log = $logPath
}

