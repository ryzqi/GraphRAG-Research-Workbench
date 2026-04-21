Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$backendDir = Join-Path $repoRoot "backend"
$backendSrcDir = Join-Path $backendDir "src"
$venvScriptsDir = Join-Path $backendDir ".venv\Scripts"
$pythonExe = Join-Path $venvScriptsDir "python.exe"
$celeryExe = Join-Path $venvScriptsDir "celery.exe"
$logsDir = Join-Path $backendDir "logs"
$envFile = Join-Path $repoRoot ".env"
$statePath = Join-Path $logsDir "deep_research_process_state.json"

function Import-DotEnv {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw ".env 未找到：$Path"
    }

    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line.Length -eq 0) { return }
        if ($line.StartsWith("#")) { return }

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
        if ($key.Length -gt 0) {
            Set-Item -Path ("Env:" + $key) -Value $value
        }
    }
}

Import-DotEnv -Path $envFile

if (-not $env:BACKEND_BIND_HOST) {
    $env:BACKEND_BIND_HOST = "0.0.0.0"
}
if (-not $env:BACKEND_PORT) {
    $env:BACKEND_PORT = "8000"
}

if (-not (Test-Path -LiteralPath $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "未找到 Python 可执行文件：$pythonExe"
}
if (-not (Test-Path -LiteralPath $celeryExe)) {
    throw "未找到 Celery 可执行文件：$celeryExe"
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backendLog = Join-Path $logsDir "backend_deep_research_e2e_$timestamp.log"
$dispatchLog = Join-Path $logsDir "worker_dispatch_deep_research_e2e_$timestamp.log"
$noncoreLog = Join-Path $logsDir "worker_noncore_deep_research_e2e_$timestamp.log"
$backendErr = Join-Path $logsDir "backend_deep_research_e2e_$timestamp.err.log"
$dispatchErr = Join-Path $logsDir "worker_dispatch_deep_research_e2e_$timestamp.err.log"
$noncoreErr = Join-Path $logsDir "worker_noncore_deep_research_e2e_$timestamp.err.log"
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = $backendSrcDir

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

$backendProc = Start-Process -FilePath $pythonExe -ArgumentList $backendArgs -WorkingDirectory $backendSrcDir -RedirectStandardOutput $backendLog -RedirectStandardError $backendErr -PassThru
$dispatchProc = Start-Process -FilePath $celeryExe -ArgumentList $dispatchArgs -WorkingDirectory $backendSrcDir -RedirectStandardOutput $dispatchLog -RedirectStandardError $dispatchErr -PassThru
$noncoreProc = Start-Process -FilePath $celeryExe -ArgumentList $noncoreArgs -WorkingDirectory $backendSrcDir -RedirectStandardOutput $noncoreLog -RedirectStandardError $noncoreErr -PassThru

$state = [pscustomobject]@{
    StartedAt = (Get-Date).ToString("o")
    BackendPid = $backendProc.Id
    DispatchPid = $dispatchProc.Id
    NoncorePid = $noncoreProc.Id
    BackendLog = $backendLog
    BackendErrLog = $backendErr
    DispatchLog = $dispatchLog
    DispatchErrLog = $dispatchErr
    NoncoreLog = $noncoreLog
    NoncoreErrLog = $noncoreErr
}

$state | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $statePath -Encoding utf8
$state | Add-Member -NotePropertyName StatePath -NotePropertyValue $statePath
$state | ConvertTo-Json -Depth 3
