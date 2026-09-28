[CmdletBinding()]
param(
    [switch]$ResetToken
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$secretDir = Join-Path $root 'agent-lab\.secrets'
$secretPath = Join-Path $secretDir 'telegram-bot-token.dpapi'
$runner = Join-Path $PSScriptRoot 'run-telegram-bridge.ps1'
$taskName = 'Agent Lab Telegram Bridge'

if (-not (Test-Path -LiteralPath $runner)) {
    throw "Telegram bridge runner was not found at $runner"
}

New-Item -ItemType Directory -Path $secretDir -Force | Out-Null

if ($ResetToken -or -not (Test-Path -LiteralPath $secretPath)) {
    Write-Output 'The token is stored encrypted for this Windows user and machine. Input is hidden.'
    $secureToken = Read-Host -Prompt 'Paste the Telegram bot token' -AsSecureString
    $tokenPointer = [IntPtr]::Zero
    try {
        $tokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
        $tokenText = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPointer)
        if ([string]::IsNullOrWhiteSpace($tokenText)) {
            throw 'No token was entered.'
        }
        $encryptedToken = ConvertFrom-SecureString -SecureString $secureToken
    }
    finally {
        if ($tokenPointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPointer)
        }
        $tokenText = $null
    }
    Set-Content -LiteralPath $secretPath -Value $encryptedToken -Encoding ASCII -NoNewline
    Write-Output "Encrypted token saved to $secretPath"
}
else {
    Write-Output "Using the existing encrypted token at $secretPath"
}

$principalId = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$powerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
$actionArguments = '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $runner

$action = New-ScheduledTaskAction -Execute $powerShell -Argument $actionArguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $principalId
$principal = New-ScheduledTaskPrincipal -UserId $principalId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew `
    -Hidden

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($null -ne $existing) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
}

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Keeps the local Agent Lab Telegram bridge running for the signed-in Windows user.' `
    -Force | Out-Null

Start-ScheduledTask -TaskName $taskName
Start-Sleep -Milliseconds 750
$info = Get-ScheduledTaskInfo -TaskName $taskName

[pscustomobject]@{
    TaskName = $taskName
    State = (Get-ScheduledTask -TaskName $taskName).State
    LastRunTime = $info.LastRunTime
    LastTaskResult = $info.LastTaskResult
    Log = (Join-Path $root 'agent-lab\telegram-bridge-logs\bridge.log')
}

