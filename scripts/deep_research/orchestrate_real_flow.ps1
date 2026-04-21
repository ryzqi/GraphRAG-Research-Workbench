param(
    [string]$Question = "请研究 2026 年值得关注的开源 AI Agent 框架趋势，并给出框架对比、适用场景和风险提示。",
    [int]$StartupWaitSeconds = 20,
    [int]$PollSeconds = 5,
    [int]$TimeoutSeconds = 1800
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$backendDir = Join-Path $repoRoot "backend"
$backendSrcDir = Join-Path $backendDir "src"
$logsDir = Join-Path $backendDir "logs"
$envFile = Join-Path $repoRoot ".env"
$pythonExe = Join-Path $backendDir ".venv\Scripts\python.exe"
$celeryExe = Join-Path $backendDir ".venv\Scripts\celery.exe"
$flowScript = Join-Path $PSScriptRoot "run_real_flow.ps1"

if (-not (Test-Path -LiteralPath $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

function Import-DotEnv {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw ".env 未找到：$Path"
    }

    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line.Length -eq 0 -or $line.StartsWith("#")) { return }
        $parts = $line.Split("=", 2)
        if ($parts.Count -ne 2) { return }
        $key = $parts[0].Trim()
        $value = $parts[1].Trim()
        if ($value.StartsWith('"') -and $value.EndsWith('"')) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        if ($value.StartsWith("'") -and $value.EndsWith("'")) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        if ($key) {
            Set-Item -Path ("Env:" + $key) -Value $value
        }
    }
}

function Stop-ProcIfRunning {
    param([int[]]$Ids)

    foreach ($procId in $Ids) {
        if (-not $procId) { continue }
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
        }
        catch {
        }
    }
}

function Wait-HttpOk {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$TimeoutSeconds = 20
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ([int]$resp.StatusCode -ge 200 -and [int]$resp.StatusCode -lt 300) {
                return $true
            }
        }
        catch {
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

Import-DotEnv -Path $envFile
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = $backendSrcDir

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backendLog = Join-Path $logsDir "backend_orch_$timestamp.log"
$backendErr = Join-Path $logsDir "backend_orch_$timestamp.err.log"
$dispatchLog = Join-Path $logsDir "worker_dispatch_orch_$timestamp.log"
$dispatchErr = Join-Path $logsDir "worker_dispatch_orch_$timestamp.err.log"
$noncoreLog = Join-Path $logsDir "worker_noncore_orch_$timestamp.log"
$noncoreErr = Join-Path $logsDir "worker_noncore_orch_$timestamp.err.log"

$backendArgs = @(
    "-m", "uvicorn",
    "app.main:app",
    "--host", "127.0.0.1",
    "--port", "8000",
    "--loop", "app.core.uvicorn_loop:windows_selector_loop_factory"
)
$dispatchArgs = @(
    "-A", "app.worker.celery_app",
    "worker",
    "-n", "worker.dispatch@%h",
    "--pool=threads",
    "--concurrency=2",
    "--prefetch-multiplier=1",
    "-Q", "dispatch"
)
$noncoreArgs = @(
    "-A", "app.worker.celery_app",
    "worker",
    "-n", "worker.noncore@%h",
    "--pool=threads",
    "--concurrency=2",
    "--prefetch-multiplier=1",
    "-Q", "research,export"
)

$backendProc = $null
$dispatchProc = $null
$noncoreProc = $null

try {
    $backendProc = Start-Process -FilePath $pythonExe -ArgumentList $backendArgs -WorkingDirectory $backendSrcDir -RedirectStandardOutput $backendLog -RedirectStandardError $backendErr -PassThru
    $dispatchProc = Start-Process -FilePath $celeryExe -ArgumentList $dispatchArgs -WorkingDirectory $backendSrcDir -RedirectStandardOutput $dispatchLog -RedirectStandardError $dispatchErr -PassThru
    $noncoreProc = Start-Process -FilePath $celeryExe -ArgumentList $noncoreArgs -WorkingDirectory $backendSrcDir -RedirectStandardOutput $noncoreLog -RedirectStandardError $noncoreErr -PassThru

    Start-Sleep -Seconds 2
    if ($backendProc.HasExited) {
        throw "backend 进程启动后立即退出"
    }
    if ($dispatchProc.HasExited) {
        throw "dispatch worker 启动后立即退出"
    }
    if ($noncoreProc.HasExited) {
        throw "noncore worker 启动后立即退出"
    }

    if (-not (Wait-HttpOk -Url "http://127.0.0.1:8000/api/v1/health" -TimeoutSeconds $StartupWaitSeconds)) {
        throw "后端健康检查未通过"
    }

    & $flowScript -Question $Question -PollSeconds $PollSeconds -TimeoutSeconds $TimeoutSeconds
}
finally {
    Stop-ProcIfRunning -Ids @(
        if ($backendProc) { $backendProc.Id }
        if ($dispatchProc) { $dispatchProc.Id }
        if ($noncoreProc) { $noncoreProc.Id }
    )

    [pscustomobject]@{
        backend_log = $backendLog
        backend_err = $backendErr
        dispatch_log = $dispatchLog
        dispatch_err = $dispatchErr
        noncore_log = $noncoreLog
        noncore_err = $noncoreErr
    } | ConvertTo-Json -Depth 4
}
