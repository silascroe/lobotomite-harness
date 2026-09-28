[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Prompt,

    [switch]$Think,

    [int]$MaxTokens = 300,

    [int]$Port = 8080
)

$ErrorActionPreference = 'Stop'

$mode = if ($Think) { '/think' } else { '/no_think' }
$body = @{
    model = 'Qwen3-8B-Q4_K_M'
    messages = @(
        @{
            role = 'user'
            content = "$($Prompt.Trim())`n$mode"
        }
    )
    temperature = if ($Think) { 0.6 } else { 0.7 }
    top_p = if ($Think) { 0.95 } else { 0.8 }
    top_k = 20
    max_tokens = $MaxTokens
    stream = $false
} | ConvertTo-Json -Depth 10

try {
    $response = Invoke-RestMethod `
        -UseBasicParsing `
        -Method Post `
        -Uri "http://127.0.0.1:$Port/v1/chat/completions" `
        -ContentType 'application/json' `
        -Body $body
}
catch {
    throw "Could not reach the local Qwen3 server on port $Port. Run scripts\start-qwen3-local.ps1 first. Original error: $($_.Exception.Message)"
}

$message = $response.choices[0].message
[pscustomobject]@{
    Content = $message.content
    Reasoning = $message.reasoning_content
    FinishReason = $response.choices[0].finish_reason
    Usage = $response.usage
} | ConvertTo-Json -Depth 10

