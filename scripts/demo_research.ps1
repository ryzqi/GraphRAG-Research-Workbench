param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$Question = "请概述当前 Deep Research session contract，并说明 metrics_snapshot / gate_snapshot 的用途。",
    [switch]$AllowExternal = $true,
    [switch]$RequireConfirmation = $true,
    [switch]$SkipInterruptResume,
    [switch]$DryRun,
    [string]$OutputDir = "",
    [int]$TimeoutSec = 30
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $OutputDir) {
    $OutputDir = Join-Path $repoRoot "tmp\research-demo"
}

function Write-Step {
    param([string]$Message)
    Write-Host "[demo_research] $Message" -ForegroundColor Cyan
}

function Invoke-JsonRequest {
    param(
        [ValidateSet("GET", "POST")]
        [string]$Method,
        [string]$Uri,
        [object]$Body = $null,
        [hashtable]$Headers = @{}
    )

    if ($Method -eq "GET") {
        return Invoke-RestMethod -Method Get -Uri $Uri -Headers $Headers -TimeoutSec $TimeoutSec
    }

    $jsonBody = if ($null -eq $Body) { $null } else { $Body | ConvertTo-Json -Depth 20 }
    return Invoke-RestMethod -Method Post -Uri $Uri -Headers $Headers -ContentType "application/json; charset=utf-8" -Body $jsonBody -TimeoutSec $TimeoutSec
}

function Get-ResearchStreamContent {
    param(
        [string]$SessionId,
        [string]$LastEventId = "",
        [string]$ResumeFromEventId = ""
    )

    $headers = @{}
    if ($LastEventId) {
        $headers["Last-Event-ID"] = $LastEventId
    }

    $uri = "$BaseUrl/api/v1/research/sessions/$SessionId/stream"
    if ($ResumeFromEventId) {
        $uri = "$uri?resume_from_event_id=$([uri]::EscapeDataString($ResumeFromEventId))"
    }

    $response = Invoke-WebRequest -Method Get -Uri $uri -Headers $headers -TimeoutSec $TimeoutSec
    return $response.Content
}

function Get-LastEventIdFromSse {
    param([string]$Content)

    if (-not $Content) {
        return $null
    }

    $matches = [regex]::Matches($Content, '"event_id"\s*:\s*"([^"]+)"')
    if ($matches.Count -eq 0) {
        return $null
    }
    return $matches[$matches.Count - 1].Groups[1].Value
}

function Get-EventTypesFromSse {
    param([string]$Content)

    if (-not $Content) {
        return @()
    }

    $matches = [regex]::Matches($Content, '"event_type"\s*:\s*"([^"]+)"')
    if ($matches.Count -eq 0) {
        return @()
    }
    return @($matches | ForEach-Object { $_.Groups[1].Value })
}

function Wait-ResearchEvent {
    param(
        [string]$SessionId,
        [string]$ExpectedEventType,
        [int]$WaitSec = 30
    )

    $deadline = (Get-Date).AddSeconds($WaitSec)
    while ((Get-Date) -lt $deadline) {
        $content = Get-ResearchStreamContent -SessionId $SessionId
        $eventTypes = @(Get-EventTypesFromSse -Content $content)
        if ($eventTypes -contains $ExpectedEventType) {
            return $content
        }
        if ($eventTypes -contains "research.run.failed") {
            throw "研究会话在等待事件 $ExpectedEventType 时失败。"
        }
        Start-Sleep -Milliseconds 250
    }

    throw "等待研究事件超时：$ExpectedEventType"
}

function Save-Json {
    param(
        [string]$Path,
        [object]$Value
    )
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    $Value | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $Path -Encoding utf8
}

$createBody = @{
    question = $Question
    allow_external = [bool]$AllowExternal
    require_confirmation = [bool]$RequireConfirmation
    plan_first = $true
}

if ($DryRun) {
    Write-Step "Dry-run mode"
    Write-Host "POST $BaseUrl/api/v1/research/sessions"
    Write-Host ($createBody | ConvertTo-Json -Depth 10)
    Write-Host "POST $BaseUrl/api/v1/research/sessions/{session_id}/confirm-plan"
    Write-Host "GET  $BaseUrl/api/v1/research/sessions/{session_id}/stream"
    if (-not $SkipInterruptResume) {
        Write-Host "POST $BaseUrl/api/v1/research/sessions/{session_id}/interrupt"
        Write-Host "POST $BaseUrl/api/v1/research/sessions/{session_id}/resume"
    }
    Write-Host "GET  $BaseUrl/api/v1/research/sessions/{session_id}/artifacts"
    exit 0
}

if (-not (Test-Path -LiteralPath $OutputDir)) {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
}

Write-Step "Create research session"
$createResponse = Invoke-JsonRequest -Method POST -Uri "$BaseUrl/api/v1/research/sessions" -Body $createBody
$sessionId = [string]$createResponse.session_id
if (-not $sessionId) {
    throw "创建 research session 失败：响应中缺少 session_id"
}
Save-Json -Path (Join-Path $OutputDir "01-create-session.json") -Value $createResponse
Write-Step "session_id=$sessionId"

$confirmationRequired = $false
if ($createResponse.plan_snapshot -and $null -ne $createResponse.plan_snapshot.confirmation_required) {
    $confirmationRequired = [bool]$createResponse.plan_snapshot.confirmation_required
}

if ($RequireConfirmation -or $confirmationRequired) {
    Write-Step "Confirm research plan"
    $confirmBody = @{
        approved = $true
        note = "demo_research.ps1 auto-confirm"
    }
    $confirmResponse = Invoke-JsonRequest -Method POST -Uri "$BaseUrl/api/v1/research/sessions/$sessionId/confirm-plan" -Body $confirmBody
    Save-Json -Path (Join-Path $OutputDir "02-confirm-plan.json") -Value $confirmResponse
}

Write-Step "Fetch current stream snapshot"
$streamContent = Get-ResearchStreamContent -SessionId $sessionId
Set-Content -LiteralPath (Join-Path $OutputDir "03-stream-initial.txt") -Value $streamContent -Encoding utf8
$eventTypes = @(Get-EventTypesFromSse -Content $streamContent)

if (-not $SkipInterruptResume) {
    if (-not ($eventTypes -contains "research.run.started") -and -not ($eventTypes -contains "research.final.completed")) {
        Write-Step "Wait for research runtime to start"
        $streamContent = Wait-ResearchEvent -SessionId $sessionId -ExpectedEventType "research.run.started" -WaitSec $TimeoutSec
        Set-Content -LiteralPath (Join-Path $OutputDir "03-stream-initial.txt") -Value $streamContent -Encoding utf8
        $eventTypes = @(Get-EventTypesFromSse -Content $streamContent)
    }

    $lastEventId = Get-LastEventIdFromSse -Content $streamContent
    if ($lastEventId) {
        Write-Step "Last event id: $lastEventId"
    }

    if ($eventTypes -contains "research.final.completed") {
        Write-Step "Research already completed before interrupt window; skip interrupt/resume"
    }
    else {
    Write-Step "Interrupt research session"
    $interruptResponse = Invoke-JsonRequest -Method POST -Uri "$BaseUrl/api/v1/research/sessions/$sessionId/interrupt" -Body @{ reason = "demo_research.ps1 interrupt checkpoint" }
    Save-Json -Path (Join-Path $OutputDir "04-interrupt.json") -Value $interruptResponse

    $resumeEventId = if ($lastEventId) { $lastEventId } else { "" }
    Write-Step "Resume research session"
    $resumeBody = @{
        idempotency_key = "demo-resume-$([DateTimeOffset]::Now.ToUnixTimeSeconds())"
        resume_from_event_id = $resumeEventId
        decisions = @(
            @{
                action = "approve"
                scope = "research"
            }
        )
    }
    $resumeResponse = Invoke-JsonRequest -Method POST -Uri "$BaseUrl/api/v1/research/sessions/$sessionId/resume" -Body $resumeBody
    Save-Json -Path (Join-Path $OutputDir "05-resume.json") -Value $resumeResponse

    Write-Step "Fetch resumed stream snapshot"
    $resumeStreamContent = Get-ResearchStreamContent -SessionId $sessionId -LastEventId $resumeEventId
    Set-Content -LiteralPath (Join-Path $OutputDir "06-stream-resumed.txt") -Value $resumeStreamContent -Encoding utf8
        $streamContent = $resumeStreamContent
    }
}

Write-Step "Wait for final report"
$finalStreamContent = Wait-ResearchEvent -SessionId $sessionId -ExpectedEventType "research.final.completed" -WaitSec $TimeoutSec
Set-Content -LiteralPath (Join-Path $OutputDir "07-stream-final.txt") -Value $finalStreamContent -Encoding utf8

Write-Step "Fetch research artifacts"
$artifactsResponse = Invoke-JsonRequest -Method GET -Uri "$BaseUrl/api/v1/research/sessions/$sessionId/artifacts"
Save-Json -Path (Join-Path $OutputDir "08-artifacts.json") -Value $artifactsResponse

$artifactKeys = @()
if ($artifactsResponse.items) {
    $artifactKeys = @($artifactsResponse.items | ForEach-Object { $_.artifact_key })
}
Write-Step ("Artifacts: " + ($artifactKeys -join ", "))
Write-Step "Demo flow finished"
