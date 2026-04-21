param(
    [string]$Question = "请研究 2026 年值得关注的开源 AI Agent 框架趋势，并给出框架对比、适用场景和风险提示。",
    [int]$PollSeconds = 5,
    [int]$TimeoutSeconds = 1800
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$backendDir = Join-Path $repoRoot "backend"
$logsDir = Join-Path $backendDir "logs"
if (-not (Test-Path -LiteralPath $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$flowLogPath = Join-Path $logsDir "deep_research_e2e_flow_$timestamp.json"
$exportPath = Join-Path $logsDir "deep_research_export_$timestamp.pdf"
$baseUrl = "http://127.0.0.1:8000/api/v1"

function Invoke-ApiJson {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("GET", "POST")] [string]$Method,
        [Parameter(Mandatory = $true)][string]$Url,
        [object]$Body = $null,
        [hashtable]$Headers = @{}
    )

    $jsonBody = $null
    if ($null -ne $Body) {
        $jsonBody = $Body | ConvertTo-Json -Depth 20
    }

    $params = @{
        Method = $Method
        Uri = $Url
        Headers = $Headers
        TimeoutSec = 120
        SkipHttpErrorCheck = $true
    }
    if ($null -ne $jsonBody) {
        $params["Body"] = $jsonBody
        $params["ContentType"] = "application/json; charset=utf-8"
    }

    try {
        $resp = Invoke-WebRequest @params
        $contentText = [string]$resp.Content
        $parsed = $null
        if ($contentText) {
            try {
                $parsed = $contentText | ConvertFrom-Json -Depth 50
            }
            catch {
                $parsed = $contentText
            }
        }
        $statusCode = [int]$resp.StatusCode
        return [pscustomobject]@{
            Ok = ($statusCode -ge 200 -and $statusCode -lt 300)
            StatusCode = $statusCode
            Headers = $resp.Headers
            Body = $parsed
            Raw = $contentText
        }
    }
    catch {
        $resp = $_.Exception.Response
        $statusCode = if ($resp -and $resp.StatusCode) { [int]$resp.StatusCode } else { -1 }
        $contentText = $null
        if ($resp) {
            try {
                $stream = $resp.GetResponseStream()
                if ($stream) {
                    $reader = New-Object System.IO.StreamReader($stream)
                    $contentText = $reader.ReadToEnd()
                    $reader.Dispose()
                }
            }
            catch {
            }
        }
        $parsed = $contentText
        if ($contentText) {
            try {
                $parsed = $contentText | ConvertFrom-Json -Depth 50
            }
            catch {
            }
        }
        return [pscustomobject]@{
            Ok = $false
            StatusCode = $statusCode
            Headers = @{}
            Body = $parsed
            Raw = $contentText
            Error = $_.Exception.Message
        }
    }
}

function Add-StepLog {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][object]$Data
    )

    $script:Flow.steps.Add([pscustomobject]@{
        timestamp = (Get-Date).ToString("o")
        step = $Name
        data = $Data
    }) | Out-Null
    $serialized = $script:Flow | ConvertTo-Json -Depth 50
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            [System.IO.File]::WriteAllText(
                $flowLogPath,
                $serialized,
                [System.Text.UTF8Encoding]::new($false)
            )
            break
        }
        catch {
            if ($attempt -eq 5) {
                throw
            }
            Start-Sleep -Milliseconds (100 * $attempt)
        }
    }
}

function Get-ArtifactMap {
    param([Parameter(Mandatory = $true)][object]$ArtifactsResponse)

    $map = @{}
    foreach ($item in @($ArtifactsResponse.items)) {
        $map[[string]$item.artifact_key] = $item
    }
    return $map
}

function Resolve-ClarificationAnswer {
    param([Parameter(Mandatory = $true)][object]$ClarificationRequest)

    $questions = @($ClarificationRequest.questions)
    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($q in $questions) {
        $questionText = [string]$q.question
        if ($questionText -match "时间|年份|周期") {
            $parts.Add("时间范围：聚焦 2026 年至今，并在必要时补充 2025 年底的延续趋势。")
            continue
        }
        if ($questionText -match "受众|面向谁|读者") {
            $parts.Add("受众：面向需要选型的工程团队与技术负责人。")
            continue
        }
        if ($questionText -match "比较|维度|关注点") {
            $parts.Add("比较维度：架构能力、工具生态、部署复杂度、可靠性、可观测性、成本与风险。")
            continue
        }
        if ($questionText -match "输出|报告|格式") {
            $parts.Add("输出要求：给出结构化对比表、结论建议与风险提示。")
            continue
        }
        $parts.Add("补充说明：如无额外限制，请采用面向工程选型的保守假设并继续推进。")
    }
    if ($parts.Count -eq 0) {
        $parts.Add("请采用面向工程选型的保守假设继续推进，聚焦 2026 年开源 AI Agent 框架趋势、对比和风险。")
    }
    return ($parts -join "`n")
}

$script:Flow = [ordered]@{
    started_at = (Get-Date).ToString("o")
    question = $Question
    flow_log_path = $flowLogPath
    export_path = $exportPath
    steps = New-Object System.Collections.ArrayList
}

$health = Invoke-ApiJson -Method GET -Url "$baseUrl/health"
Add-StepLog -Name "health" -Data $health
if (-not $health.Ok) {
    throw "后端 /health 不可用：$($health | ConvertTo-Json -Depth 10)"
}

$ready = Invoke-ApiJson -Method GET -Url "$baseUrl/ready"
Add-StepLog -Name "ready" -Data $ready
if (-not $ready.Ok) {
    throw "后端 /ready 不可用：$($ready | ConvertTo-Json -Depth 10)"
}

$modelConfig = Invoke-ApiJson -Method GET -Url "$baseUrl/model-config"
Add-StepLog -Name "model_config" -Data $modelConfig

$createResp = Invoke-ApiJson -Method POST -Url "$baseUrl/research/sessions" -Body @{
    question = $Question
    plan_first = $true
}
Add-StepLog -Name "create_session" -Data $createResp
if (-not $createResp.Ok) {
    throw "创建 research session 失败"
}

$sessionId = [string]$createResp.Body.session_id
$status = [string]$createResp.Body.status
$current = $createResp.Body

while ($status -eq "clarifying") {
    $answer = Resolve-ClarificationAnswer -ClarificationRequest $current.clarification_request
    Add-StepLog -Name "clarification_answer_prepared" -Data @{
        session_id = $sessionId
        answer = $answer
    }

    $clarifyResp = Invoke-ApiJson -Method POST -Url "$baseUrl/research/sessions/$sessionId/clarification" -Body @{
        answer = $answer
    }
    Add-StepLog -Name "submit_clarification" -Data $clarifyResp
    if (-not $clarifyResp.Ok) {
        throw "提交 clarification 失败"
    }
    $current = $clarifyResp.Body
    $status = [string]$current.status
}

if ($status -ne "plan_ready") {
    throw "澄清后未进入 plan_ready，当前状态=$status"
}

$startResp = Invoke-ApiJson -Method POST -Url "$baseUrl/research/sessions/$sessionId/start"
Add-StepLog -Name "start_session" -Data $startResp
if (-not $startResp.Ok) {
    throw "启动研究失败"
}

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$lastArtifacts = $null
$lastStream = $null
$terminalStatus = $null
$reportReady = $false

while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds $PollSeconds

    $streamResp = Invoke-ApiJson -Method GET -Url "$baseUrl/research/sessions/$sessionId/stream"
    Add-StepLog -Name "poll_stream" -Data $streamResp
    $lastStream = $streamResp

    $artifactsResp = Invoke-ApiJson -Method GET -Url "$baseUrl/research/sessions/$sessionId/artifacts"
    Add-StepLog -Name "poll_artifacts" -Data $artifactsResp
    if (-not $artifactsResp.Ok) {
        $lastArtifacts = $artifactsResp
        continue
    }

    $lastArtifacts = $artifactsResp
    $terminalStatus = [string]$artifactsResp.Body.status
    $artifactMap = Get-ArtifactMap -ArtifactsResponse $artifactsResp.Body
    $reportReady = $artifactMap.ContainsKey("report_md") -and $artifactMap.ContainsKey("report_json")

    if ($terminalStatus -eq "final" -and $reportReady) {
        break
    }
    if ($terminalStatus -in @("failed", "canceled", "timed_out")) {
        break
    }
}

if ($null -eq $lastArtifacts -or -not $lastArtifacts.Ok) {
    throw "未能成功获取 artifacts"
}

Add-StepLog -Name "final_artifacts" -Data $lastArtifacts

$finalStatus = [string]$lastArtifacts.Body.status
if ($finalStatus -ne "final") {
    throw "研究未成功完成，终态=$finalStatus"
}

$artifactMap = Get-ArtifactMap -ArtifactsResponse $lastArtifacts.Body
if (-not ($artifactMap.ContainsKey("report_md") -and $artifactMap.ContainsKey("report_json"))) {
    throw "研究终态缺少 report_md/report_json"
}

$exportCreate = Invoke-ApiJson -Method POST -Url "$baseUrl/exports" -Body @{
    type = "research"
    session_id = $sessionId
}
Add-StepLog -Name "create_export" -Data $exportCreate
if (-not $exportCreate.Ok) {
    throw "创建导出任务失败"
}

$exportId = [string]$exportCreate.Body.id
$exportDeadline = (Get-Date).AddSeconds(300)
$exportJob = $exportCreate.Body
while ((Get-Date) -lt $exportDeadline) {
    Start-Sleep -Seconds 3
    $exportGet = Invoke-ApiJson -Method GET -Url "$baseUrl/exports/$exportId"
    Add-StepLog -Name "poll_export" -Data $exportGet
    if (-not $exportGet.Ok) {
        continue
    }
    $exportJob = $exportGet.Body
    $exportStatus = [string]$exportJob.status
    if ($exportStatus -eq "succeeded") {
        break
    }
    if ($exportStatus -eq "failed") {
        throw "导出任务失败：$([string]$exportJob.error_code) $([string]$exportJob.error_message)"
    }
}

if ([string]$exportJob.status -ne "succeeded") {
    throw "导出任务超时未完成"
}

Invoke-WebRequest -Method GET -Uri "$baseUrl/exports/$exportId/download" -OutFile $exportPath -TimeoutSec 120 | Out-Null
Add-StepLog -Name "download_export" -Data @{
    export_id = $exportId
    export_path = $exportPath
    file_size = (Get-Item -LiteralPath $exportPath).Length
}

$summary = [pscustomobject]@{
    completed_at = (Get-Date).ToString("o")
    session_id = $sessionId
    final_status = $finalStatus
    export_id = $exportId
    export_path = $exportPath
    flow_log_path = $flowLogPath
    report_keys = @($artifactMap.Keys | Sort-Object)
}
Add-StepLog -Name "summary" -Data $summary
$summary | ConvertTo-Json -Depth 20
