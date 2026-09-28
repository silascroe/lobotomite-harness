[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Prompt,

    [switch]$NoThink,

    [int]$MaxTokens = 1200,

    [int]$Port = 8080,

    [ValidateSet('E2B', 'E4B')]
    [string]$ModelSize = 'E4B'
)

$ErrorActionPreference = 'Stop'

$messages = @()
if (-not $NoThink) {
    $messages += @{
        role = 'system'
        content = '<|think|>'
    }
}
$messages += @{
    role = 'user'
    content = $Prompt.Trim()
}

$body = @{
    model = "Gemma-4-$ModelSize-Q4_0"
    messages = $messages
    temperature = 1.0
    top_p = 0.95
    top_k = 64
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
    throw "Could not reach the local Gemma 4 $ModelSize server on port $Port. Run scripts\start-gemma4-local.ps1 -ModelSize $ModelSize first. Original error: $($_.Exception.Message)"
}

$message = $response.choices[0].message
[pscustomobject]@{
    Content = $message.content
    Reasoning = $message.reasoning_content
    FinishReason = $response.choices[0].finish_reason
    Usage = $response.usage
} | ConvertTo-Json -Depth 10

