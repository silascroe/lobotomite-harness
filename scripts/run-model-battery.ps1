[CmdletBinding()]
param(
    [int]$Port = 8080,
    [int]$Context = 8192,
    [int]$MaxTokens = 700,
    [int]$GemmaReasoningBudget = 1024,
    [string]$Output = 'agent-lab\benchmarks\model-battery-20260919.json'
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$outputPath = if ([IO.Path]::IsPathRooted($Output)) { $Output } else { Join-Path $root $Output }
$commonSystem = @'
You are being evaluated as a local assistant on a modest Windows PC. Follow the user's instructions exactly. Be concise but complete. Separate what you know from what you are guessing. Do not claim to have inspected files, run commands, or used tools unless the prompt explicitly says you did. Use plain language, no emojis, and a restrained dry voice only when it fits. Do not reveal hidden reasoning; provide conclusions and useful checks instead.
'@

$tests = @(
    [pscustomobject]@{
        Id = 'personality'; Category = 'personality';
        Prompt = 'In exactly three sentences, explain what kind of assistant you are. Be warm but unsentimental, include at most one restrained dry aside, and use no emojis.'
    },
    [pscustomobject]@{
        Id = 'instruction-json'; Category = 'instruction following';
        Prompt = 'Return exactly one JSON object with exactly these keys: answer, caveat, confidence. Set answer to the result of 7 multiplied by 8, caveat to a short phrase, and confidence to a number between 0 and 1. Do not use Markdown fences or any text outside the JSON object.'
    },
    [pscustomobject]@{
        Id = 'logic'; Category = 'reasoning';
        Prompt = 'Three boxes are labeled APPLES, ORANGES, and MIXED. Every label is wrong. You may take one fruit from one box without looking inside. Which box do you draw from, and how do you relabel all three boxes? Explain briefly.'
    },
    [pscustomobject]@{
        Id = 'coding'; Category = 'coding';
        Prompt = 'Write a Python function dedupe_preserve_order(items) that removes duplicates while preserving first-seen order. Include a two-sentence explanation, time and space complexity, and three tiny example calls. Keep the answer under 180 words.'
    },
    [pscustomobject]@{
        Id = 'debugging'; Category = 'debugging';
        Prompt = @'
Diagnose this JavaScript bug and give the smallest corrected version:

function last(items) {
  for (let i = 0; i <= items.length; i++) {
    if (items[i]) return items[i];
  }
}

The intended behavior is to return the final item in the array, or undefined for an empty array. Explain the bug in two sentences, then show corrected code.
'@
    },
    [pscustomobject]@{
        Id = 'honesty'; Category = 'calibration';
        Prompt = 'I told you I have an i5-8400, 32 GB of DDR4 RAM, and a GTX 1070. Without inspecting the machine, state three things you can reasonably infer and three things you cannot infer. Do not invent exact clock speeds, temperatures, driver versions, or current memory usage.'
    },
    [pscustomobject]@{
        Id = 'ambiguity'; Category = 'judgment';
        Prompt = 'I want a script to back up my project folder. Before writing code, list the three most important ambiguities you need resolved and give one safe default for each. Do not pretend the missing details are known.'
    },
    [pscustomobject]@{
        Id = 'summarize'; Category = 'communication';
        Prompt = 'Summarize this in four bullets, then give one practical recommendation: A local model can be fast enough for short prompts while still becoming painfully slow on long context, deep reasoning, or large file edits. VRAM capacity, context length, quantization, prompt format, and sampling settings all affect the result. A model that wins a single clever answer may still be the worse daily driver if it stalls, loses formatting, or needs repeated correction.'
    },
    [pscustomobject]@{
        Id = 'context'; Category = 'conversation memory';
        Prompt = 'Remember this exact token for the next turn: CEDAR-47. Reply only with: stored.'
        FollowUp = 'What exact token did I ask you to remember? Also give one sentence explaining why a benchmark should test memory separately from raw reasoning.'
    }
)

function Get-GpuState {
    try {
        $line = (& nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
        return [string]$line
    }
    catch {
        return ''
    }
}

function Get-LoadedModel {
    try {
        $response = Invoke-RestMethod -UseBasicParsing -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 5
        return [string]$response.data[0].id
    }
    catch {
        return ''
    }
}

function Stop-LocalModel {
    $processes = @(Get-Process -Name 'llama-server' -ErrorAction SilentlyContinue)
    foreach ($process in $processes) {
        Write-Host "Stopping llama-server PID $($process.Id)"
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if (-not (Get-Process -Name 'llama-server' -ErrorAction SilentlyContinue)) { return }
        Start-Sleep -Milliseconds 250
    }
    throw 'llama-server did not stop cleanly'
}

function Start-LocalModel([string]$Kind) {
    $timer = [Diagnostics.Stopwatch]::StartNew()
    if ($Kind -eq 'gemma') {
        & (Join-Path $root 'scripts\start-gemma4-local.ps1') -Port $Port -Context $Context -Device 'Vulkan0' -ReasoningBudget $GemmaReasoningBudget | Out-Null
    }
    else {
        & (Join-Path $root 'scripts\start-qwen3-local.ps1') -Port $Port -Context $Context -Device 'Vulkan0' | Out-Null
    }
    for ($attempt = 0; $attempt -lt 180; $attempt++) {
        try {
            $health = Invoke-RestMethod -UseBasicParsing -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
            if ($health.status -eq 'ok') {
                $timer.Stop()
                return [pscustomobject]@{
                    startup_seconds = [math]::Round($timer.Elapsed.TotalSeconds, 2)
                    model_id = Get-LoadedModel
                    gpu_after_load = Get-GpuState
                }
            }
        }
        catch { }
        Start-Sleep -Seconds 1
    }
    throw "Timed out waiting for $Kind model server"
}

function Invoke-ModelRequest([string]$Kind, [array]$Messages, [string]$TestId, [string]$Stage) {
    $modelName = if ($Kind -eq 'gemma') { 'Gemma-4-E4B-Q4_0' } else { 'Qwen3-8B-Q4_K_M' }
    $body = @{
        model = $modelName
        messages = $Messages
        temperature = if ($Kind -eq 'gemma') { 0.6 } else { 0.7 }
        top_p = if ($Kind -eq 'gemma') { 0.95 } else { 0.8 }
        top_k = 20
        max_tokens = $MaxTokens
        stream = $false
    } | ConvertTo-Json -Depth 12

    $timer = [Diagnostics.Stopwatch]::StartNew()
    try {
        $response = Invoke-RestMethod -UseBasicParsing -Method Post -Uri "http://127.0.0.1:$Port/v1/chat/completions" -ContentType 'application/json' -Body $body -TimeoutSec 300
        $timer.Stop()
        $choice = $response.choices[0]
        $message = $choice.message
        $usage = $response.usage
        return [pscustomobject]@{
            model = $Kind
            test_id = $TestId
            stage = $Stage
            status = 'ok'
            elapsed_seconds = [math]::Round($timer.Elapsed.TotalSeconds, 2)
            finish_reason = [string]$choice.finish_reason
            prompt_tokens = $usage.prompt_tokens
            completion_tokens = $usage.completion_tokens
            response = [string]$message.content
            reasoning = [string]$message.reasoning_content
            error = ''
        }
    }
    catch {
        $timer.Stop()
        return [pscustomobject]@{
            model = $Kind
            test_id = $TestId
            stage = $Stage
            status = 'error'
            elapsed_seconds = [math]::Round($timer.Elapsed.TotalSeconds, 2)
            finish_reason = ''
            prompt_tokens = $null
            completion_tokens = $null
            response = ''
            reasoning = ''
            error = $_.Exception.Message
        }
    }
}

function Test-AutomaticSignals($Test, $Result) {
    $text = [string]$Result.response
    $signals = [ordered]@{ nonempty = -not [string]::IsNullOrWhiteSpace($text) }
    if ($Test.Id -eq 'instruction-json') {
        $json = $null
        try { $json = $text.Trim() | ConvertFrom-Json -ErrorAction Stop } catch { }
        $signals.json_valid = $null -ne $json
        $signals.json_exact_keys = $false
        if ($null -ne $json) {
            $keys = @($json.psobject.Properties.Name | Sort-Object)
            $signals.json_exact_keys = (@($keys -join ',') -eq @('answer,caveat,confidence'))
        }
    }
    if ($Test.Id -eq 'logic') { $signals.mentions_mixed_box = $text -match '(?i)mixed' }
    if ($Test.Id -eq 'coding') { $signals.has_function = $text -match '(?i)def\s+dedupe_preserve_order'; $signals.has_complexity = $text -match '(?i)complexity|O\(' }
    if ($Test.Id -eq 'debugging') { $signals.identifies_bound = $text -match '(?i)<=|length\s*-\s*1'; $signals.returns_last = $text -match '(?i)items\[.*length' }
    if ($Test.Id -eq 'honesty') { $signals.has_uncertainty_language = $text -match "(?i)cannot|can't|not infer|unknown" }
    if ($Test.Id -eq 'ambiguity') { $signals.asks_before_code = $text -match '(?i)where|destination|retention|exclude|permission|schedule|platform' }
    if ($Test.Id -eq 'context') { $signals.remembers_token = $text -match 'CEDAR-47' }
    return $signals
}

function Run-Battery([string]$Kind) {
    Write-Host "`n=== $Kind ==="
    $startInfo = Start-LocalModel $Kind
    Write-Host "Loaded $($startInfo.model_id) in $($startInfo.startup_seconds)s; GPU: $($startInfo.gpu_after_load)"
    $results = @()
    foreach ($test in $tests) {
        $userPrompt = if ($Kind -eq 'qwen') { "$($test.Prompt.Trim())`n/no_think" } else { $test.Prompt.Trim() }
        $systemPrompt = if ($Kind -eq 'gemma') { "<|think|>`n$commonSystem" } else { $commonSystem }
        $messages = @(
            @{ role = 'system'; content = $systemPrompt }
            @{ role = 'user'; content = $userPrompt }
        )
        $first = Invoke-ModelRequest $Kind $messages $test.Id 'primary'
        $first | Add-Member -NotePropertyName signals -NotePropertyValue (Test-AutomaticSignals $test $first)
        $results += $first
        Write-Host ("{0,-18} {1,7}s  {2,5} output tokens  {3}" -f $test.Id, $first.elapsed_seconds, ($first.completion_tokens ?? 0), $first.status)

        if ($test.FollowUp) {
            $assistantText = if ($first.status -eq 'ok') { $first.response } else { '[no response]' }
            $followPrompt = "$($test.FollowUp.Trim())`n/no_think"
            $followMessages = @(
                @{ role = 'system'; content = $systemPrompt }
                @{ role = 'user'; content = $userPrompt }
                @{ role = 'assistant'; content = $assistantText }
                @{ role = 'user'; content = $followPrompt }
            )
            $follow = Invoke-ModelRequest $Kind $followMessages $test.Id 'follow_up'
            $follow | Add-Member -NotePropertyName signals -NotePropertyValue (Test-AutomaticSignals $test $follow)
            $results += $follow
            Write-Host ("{0,-18} {1,7}s  {2,5} output tokens  {3}" -f "$($test.Id)-follow", $follow.elapsed_seconds, ($follow.completion_tokens ?? 0), $follow.status)
        }
    }
    return [pscustomobject]@{
        model = $Kind
        startup = $startInfo
        tests = $results
    }
}

$initialModel = Get-LoadedModel
$initialKind = if ($initialModel -match '(?i)Gemma4') { 'gemma' } elseif ($initialModel -match '(?i)Qwen3') { 'qwen' } else { 'gemma' }
$suiteTimer = [Diagnostics.Stopwatch]::StartNew()
$suite = [ordered]@{
    generated_at = (Get-Date).ToString('o')
    hardware = [ordered]@{
        cpu = 'Intel Core i5-8400 (user supplied)'
        ram = '32 GB DDR4 (user supplied)'
        gpu = Get-GpuState
        context = $Context
        max_tokens = $MaxTokens
    }
    profiles = [ordered]@{
        gemma = 'Gemma 4 E4B Q4_0; reasoning on; budget 1024; temperature 0.6; top_p 0.95'
        qwen = 'Qwen3 8B Q4_K_M; /no_think; temperature 0.7; top_p 0.8'
    }
    initial_model = $initialModel
    results = @()
}

try {
    Stop-LocalModel
    $suite.results += Run-Battery 'gemma'
    Stop-LocalModel
    $suite.results += Run-Battery 'qwen'
}
finally {
    try { Stop-LocalModel } catch { }
    try {
        Write-Host "`nRestoring $initialKind server..."
        $null = Start-LocalModel $initialKind
    }
    catch {
        Write-Warning "Could not restore the initial model server: $($_.Exception.Message)"
    }
}

$suiteTimer.Stop()
$suite.elapsed_seconds = [math]::Round($suiteTimer.Elapsed.TotalSeconds, 2)
$suite.restored_model = Get-LoadedModel
$parent = Split-Path -Parent $outputPath
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$suite | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $outputPath -Encoding UTF8
Write-Host "`nSaved results to $outputPath"

