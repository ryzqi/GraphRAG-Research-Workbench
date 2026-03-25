param(
    [switch]$SkipInfra,
    [switch]$NoDetachInfra,
    [switch]$SkipBackend,
    [switch]$SkipWorker,
    [switch]$SkipFrontend,
    [switch]$SkipMigrate,
    [switch]$RunMigrate,
    [switch]$RunSeed,
    [switch]$Verbose
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"
$envFile = Join-Path $repoRoot ".env"
$isWindowsRuntime = ($env:OS -eq "Windows_NT")
if (-not $isWindowsRuntime) {
    throw "scripts/start_all.ps1 仅支持 Windows 环境。当前环境不受支持。"
}

function Import-DotEnv {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw ".env 未找到，请先复制 .env.example 到 .env 并填写。"
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

function Ensure-Command {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [string]$InstallHint = ""
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        $hint = if ($InstallHint) { " 建议：$InstallHint" } else { "" }
        throw "未找到命令 $Name。$hint"
    }
}

function Start-Terminal {
    param(
        [Parameter(Mandatory = $true)][string]$Title,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$Command
    )

    $terminalShell = "powershell"
    if (Get-Command "pwsh" -ErrorAction SilentlyContinue) {
        $terminalShell = "pwsh"
    }

    $escapedTitle = $Title.Replace("'", "''")
    $escapedCommandLiteral = $Command.Replace("'", "''")

    $scriptLines = @(
        "`$Host.UI.RawUI.WindowTitle = '$escapedTitle'"
    )
    if ($Verbose) {
        $scriptLines += "Write-Host '执行:' -ForegroundColor Yellow"
        $scriptLines += "Write-Host '$escapedCommandLiteral' -ForegroundColor DarkYellow"
    }
    $scriptLines += $Command

    $psCommand = $scriptLines -join "; "
    Start-Process -FilePath $terminalShell -ArgumentList "-NoProfile", "-NoExit", "-Command", $psCommand -WorkingDirectory $WorkingDirectory | Out-Null
}

function Normalize-ApiBaseUrl {
    param([string]$Raw)

    if (-not $Raw) { return "http://127.0.0.1:8000" }

    $value = $Raw.Trim().TrimEnd("/")
    if ($value.EndsWith("/api/v1")) {
        $value = $value.Substring(0, $value.Length - "/api/v1".Length)
    }
    return $value.TrimEnd("/")
}

function Get-HttpStatusCodeNoProxy {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$TimeoutSec = 2
    )

    $useNoProxy = $false
    try {
        $uri = [Uri]$Url
        $urlHost = $uri.Host.ToString().ToLowerInvariant()
        $useNoProxy = ($urlHost -eq "localhost") -or ($urlHost -eq "127.0.0.1") -or ($urlHost -eq "::1")
    }
    catch {
        $useNoProxy = $false
    }

    # 优先使用 curl.exe，避免 PowerShell 或系统代理差异，并可靠获取 4xx/5xx 状态码。
    if (Get-Command "curl.exe" -ErrorAction SilentlyContinue) {
        $curlArgs = @(
            "--silent"
            "--connect-timeout", "1"
            "--max-time", $TimeoutSec
            "--output", "NUL"
            "--write-out", "%{http_code}"
            $Url
        )
        if ($useNoProxy) {
            $curlArgs = @("--noproxy", "*") + $curlArgs
        }

        $code = & curl.exe @curlArgs
        if ($LASTEXITCODE -ne 0) { return -1 }
        if ($code -match '^\d+$') { return [int]$code }
        return -1
    }

    try {
        if ($useNoProxy) {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec -Proxy $null
        }
        else {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
        }
        return [int]$resp.StatusCode
    }
    catch {
        # 服务端返回非 2xx 时，Invoke-WebRequest 会抛出异常，但异常对象仍携带响应。
        $resp = $_.Exception.Response
        if ($resp -and $resp.StatusCode) {
            try { return [int]$resp.StatusCode } catch { }
        }
        return -1
    }
}

function Wait-BackendReady {
    param(
        [int]$TimeoutSeconds = 30,
        [int]$PollIntervalMs = 500
    )

    $rawApiBase = if ($env:NEXT_PUBLIC_API_BASE_URL) { $env:NEXT_PUBLIC_API_BASE_URL } else { $env:VITE_API_BASE_URL }
    $baseUrl = Normalize-ApiBaseUrl -Raw $rawApiBase
    # /ready 会检查 Postgres 等关键依赖是否可用；比 /health 更能反映“前端可用”状态。
    $healthUrl = "$baseUrl/api/v1/ready"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)

    $lastProbe = $null
    while ((Get-Date) -lt $deadline) {
        $code = Get-HttpStatusCodeNoProxy -Url $healthUrl -TimeoutSec 2
        if ($code -ge 200 -and $code -lt 300) { return $true }

        if ($Verbose) {
            $probe = if ($code -ge 0) { "HTTP $code" } else { "no response" }
            if ($probe -ne $lastProbe) {
                Write-Host "ready probe: $probe ($healthUrl)" -ForegroundColor DarkGray
                $lastProbe = $probe
            }
        }

        Start-Sleep -Milliseconds $PollIntervalMs
    }

    return $false
}

function Get-EnvVarValue {
    param([Parameter(Mandatory = $true)][string]$Name)

    $value = [Environment]::GetEnvironmentVariable($Name)
    if ($null -eq $value) { return "" }
    $trimmed = $value.Trim()
    if ($trimmed.Length -eq 0) { return "" }
    return $trimmed
}

function Resolve-CeleryNodeName {
    param([Parameter(Mandatory = $true)][string]$Template)

    $hostname = Get-EnvVarValue -Name "COMPUTERNAME"
    if (-not $hostname) {
        $hostname = [Environment]::MachineName
    }
    if (-not $hostname) {
        $hostname = "localhost"
    }

    return $Template.Replace("%h", $hostname.ToLowerInvariant())
}

function Get-CeleryWorkerCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Queues,
        [string]$NodeName = "",
        [string]$PoolEnvVar = "CELERY_WORKER_POOL",
        [string]$ConcurrencyEnvVar = "CELERY_WORKER_CONCURRENCY",
        [string]$PrefetchEnvVar = "CELERY_WORKER_PREFETCH_MULTIPLIER",
        [string]$DefaultPool = "threads",
        [string]$DefaultConcurrency = "",
        [string]$DefaultPrefetchMultiplier = ""
    )

    $explicitPool = (Get-EnvVarValue -Name $PoolEnvVar).ToLowerInvariant()
    if (-not $explicitPool) {
        $explicitPool = (Get-EnvVarValue -Name "CELERY_WORKER_POOL").ToLowerInvariant()
    }

    $pool = if ($explicitPool) {
        $explicitPool
    }
    else {
        $DefaultPool
    }

    $concurrency = Get-EnvVarValue -Name $ConcurrencyEnvVar
    if (-not $concurrency) {
        $concurrency = Get-EnvVarValue -Name "CELERY_WORKER_CONCURRENCY"
    }
    if (-not $concurrency) {
        if ($DefaultConcurrency) {
            $concurrency = $DefaultConcurrency
        }
        elseif ($pool -eq "threads") {
            $cpuCount = [Environment]::ProcessorCount
            if ($cpuCount -lt 1) { $cpuCount = 1 }
            $concurrency = [Math]::Min($cpuCount, 8).ToString()
        }
        else {
            $concurrency = "1"
        }
    }

    $prefetchMultiplier = Get-EnvVarValue -Name $PrefetchEnvVar
    if (-not $prefetchMultiplier) {
        $prefetchMultiplier = Get-EnvVarValue -Name "CELERY_WORKER_PREFETCH_MULTIPLIER"
    }
    if (-not $prefetchMultiplier -and $DefaultPrefetchMultiplier) {
        $prefetchMultiplier = $DefaultPrefetchMultiplier
    }

    $prefetchArgs = ""
    if ($prefetchMultiplier) {
        $prefetchArgs = " --prefetch-multiplier=$prefetchMultiplier"
    }

    $startupFlags = Get-EnvVarValue -Name "CELERY_WORKER_STARTUP_FLAGS"
    if (-not $startupFlags) {
        # Windows 下的 Celery 仅按尽力而为模式运行，关闭 mingle/gossip 以减少启动延迟和噪声。
        $startupFlags = "--without-mingle --without-gossip"
    }

    $nodeArgs = ""
    if ($NodeName) {
        $nodeArgs = " -n $NodeName"
    }

    if ($Verbose) {
        $resolvedPrefetch = if ($prefetchMultiplier) { $prefetchMultiplier } else { "celery-default" }
        Write-Host "Celery Worker 参数：--pool=$pool --concurrency=$concurrency --prefetch-multiplier=$resolvedPrefetch $startupFlags -Q $Queues" -ForegroundColor DarkGray
    }

    return "uv run celery -A app.worker.celery_app worker --loglevel=INFO$nodeArgs --pool=$pool --concurrency=$concurrency$prefetchArgs $startupFlags -Q $Queues"
}
function Get-CeleryBeatCommand {
    return "uv run celery -A app.worker.celery_app beat --loglevel=INFO"
}
function Get-BackendApiCommand {
    $command = "uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --loop app.core.uvicorn_loop:windows_selector_loop_factory"
    if ($Verbose) {
        Write-Host "后端 API 参数：--loop app.core.uvicorn_loop:windows_selector_loop_factory（Windows 强制 SelectorEventLoop，兼容 psycopg）" -ForegroundColor DarkGray
    }
    return $command
}

function Get-CeleryWorkerNodeOnlineMap {
    param(
        [string[]]$WorkerNodeNames = @()
    )

    $onlineMap = @{}
    foreach ($nodeName in $WorkerNodeNames) {
        if (-not $nodeName) { continue }
        $onlineMap[$nodeName] = $false
    }
    if ($onlineMap.Count -eq 0) {
        return $onlineMap
    }

    $candidates = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -and
        $_.CommandLine.Contains(" worker ") -and
        ($_.CommandLine.Contains("app.worker.celery_app") -or $_.CommandLine.Contains(" celery "))
    }

    foreach ($proc in $candidates) {
        $commandLine = [string]$proc.CommandLine
        foreach ($nodeName in @($onlineMap.Keys)) {
            if ($onlineMap[$nodeName]) { continue }
            if ($commandLine.Contains("-n $nodeName")) {
                $onlineMap[$nodeName] = $true
            }
        }
    }

    return $onlineMap
}

function Wait-CeleryWorkersOnline {
    param(
        [int]$TimeoutSeconds = 60,
        [string[]]$WorkerNodeNames = @()
    )

    if ($WorkerNodeNames.Count -eq 0) { return $true }
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $onlineMap = Get-CeleryWorkerNodeOnlineMap -WorkerNodeNames $WorkerNodeNames
        $offlineNodes = @()
        foreach ($nodeName in $WorkerNodeNames) {
            if (-not $nodeName) { continue }
            if (-not $onlineMap.ContainsKey($nodeName) -or -not [bool]$onlineMap[$nodeName]) {
                $offlineNodes += $nodeName
            }
        }

        if ($offlineNodes.Count -eq 0) {
            if ($Verbose) {
                Write-Host "Celery Worker 进程已就绪：$($WorkerNodeNames -join ', ')" -ForegroundColor DarkGray
            }
            return $true
        }

        if ($Verbose) {
            Write-Host "等待 Celery Worker 进程就绪，缺失节点：$($offlineNodes -join ', ')" -ForegroundColor DarkGray
        }

        Start-Sleep -Milliseconds 1000
    }
    return $false
}

Write-Host "加载环境变量 (.env) ..." -ForegroundColor Cyan
Import-DotEnv -Path $envFile

if (-not $env:NEXT_PUBLIC_API_BASE_URL -and $env:VITE_API_BASE_URL) {
    $env:NEXT_PUBLIC_API_BASE_URL = Normalize-ApiBaseUrl -Raw $env:VITE_API_BASE_URL
    if ($Verbose) {
        Write-Host "检测到旧变量 VITE_API_BASE_URL，已映射到 NEXT_PUBLIC_API_BASE_URL=$($env:NEXT_PUBLIC_API_BASE_URL)" -ForegroundColor DarkGray
    }
}

$env:PYTHONUNBUFFERED = "1"
$shouldRunMigrate = $RunMigrate -and (-not $SkipMigrate)
if ($SkipMigrate -and $RunMigrate) {
    Write-Host "检测到 -RunMigrate 与 -SkipMigrate 同时传入，按 -SkipMigrate 优先，跳过迁移。" -ForegroundColor Yellow
}

if (-not $SkipInfra) {
    Write-Host "启动基础依赖 (Podman) ..." -ForegroundColor Green
    $infraScript = Join-Path $repoRoot "infra\up.ps1"
    if (-not (Test-Path -LiteralPath $infraScript)) {
        throw "未找到 infra/up.ps1。"
    }
    $infraArgs = @()
    if ($NoDetachInfra) { $infraArgs += "-NoDetach" }
    & $infraScript @infraArgs
}

$needBackend = (-not $SkipBackend) -or (-not $SkipWorker) -or $RunSeed -or $shouldRunMigrate
if ($needBackend) {
    Ensure-Command -Name "uv" -InstallHint "pip install uv"
    Push-Location $backendDir
    try {
        if (-not (Test-Path (Join-Path $backendDir ".venv"))) {
            Write-Host "检测到缺少 backend/.venv，执行 uv sync 安装依赖..." -ForegroundColor Yellow
            uv sync
            if ($LASTEXITCODE -ne 0) {
                throw "uv sync 失败（exit=$LASTEXITCODE）"
            }
        }
        elseif ($Verbose) {
            Write-Host "已检测到 backend/.venv，跳过 uv sync" -ForegroundColor DarkGray
        }

        if ($shouldRunMigrate) {
            Write-Host "执行数据库迁移 (alembic upgrade head)..." -ForegroundColor Yellow
            uv run alembic upgrade head
            if ($LASTEXITCODE -ne 0) {
                throw "数据库迁移失败（exit=$LASTEXITCODE）。若本地数据库来自旧迁移链，请先重置 schema 后再执行 -RunMigrate。"
            }
        }
        else {
            Write-Host "默认跳过数据库迁移；如需迁移请添加 -RunMigrate。" -ForegroundColor DarkGray
        }
    }
    finally {
        Pop-Location
    }
}

if (-not $SkipBackend) {
    $backendCommand = Get-BackendApiCommand
    Start-Terminal -Title "backend-api" -WorkingDirectory $backendDir -Command $backendCommand
}

if (-not $SkipWorker) {
    $beatCommand = Get-CeleryBeatCommand
    Start-Terminal -Title "celery-beat" -WorkingDirectory $backendDir -Command $beatCommand

    $dispatchWorkerNodeName = Resolve-CeleryNodeName -Template "worker.dispatch@%h"
    $coreWorkerNodeName = Resolve-CeleryNodeName -Template "worker.core@%h"
    $nonCoreWorkerNodeName = Resolve-CeleryNodeName -Template "worker.noncore@%h"

    $dispatchWorkerCommand = Get-CeleryWorkerCommand -Queues "dispatch" -NodeName $dispatchWorkerNodeName -PoolEnvVar "CELERY_DISPATCH_WORKER_POOL" -ConcurrencyEnvVar "CELERY_DISPATCH_WORKER_CONCURRENCY" -PrefetchEnvVar "CELERY_DISPATCH_WORKER_PREFETCH_MULTIPLIER" -DefaultConcurrency "2" -DefaultPrefetchMultiplier "1"
    Start-Terminal -Title "celery-worker-dispatch" -WorkingDirectory $backendDir -Command $dispatchWorkerCommand

    $coreWorkerCommand = Get-CeleryWorkerCommand -Queues "ingestion,rebuild,default" -NodeName $coreWorkerNodeName -PoolEnvVar "CELERY_CORE_WORKER_POOL" -ConcurrencyEnvVar "CELERY_CORE_WORKER_CONCURRENCY" -PrefetchEnvVar "CELERY_CORE_WORKER_PREFETCH_MULTIPLIER" -DefaultPrefetchMultiplier "1"
    Start-Terminal -Title "celery-worker-core" -WorkingDirectory $backendDir -Command $coreWorkerCommand

    $nonCoreWorkerCommand = Get-CeleryWorkerCommand -Queues "research,export" -NodeName $nonCoreWorkerNodeName -PoolEnvVar "CELERY_NONCORE_WORKER_POOL" -ConcurrencyEnvVar "CELERY_NONCORE_WORKER_CONCURRENCY" -PrefetchEnvVar "CELERY_NONCORE_WORKER_PREFETCH_MULTIPLIER" -DefaultConcurrency "2" -DefaultPrefetchMultiplier "1"
    Start-Terminal -Title "celery-worker-noncore" -WorkingDirectory $backendDir -Command $nonCoreWorkerCommand

    Write-Host "等待 Celery Worker 进程就绪（dispatch / core）..." -ForegroundColor Cyan
    Push-Location $backendDir
    try {
        $celeryWorkersReady = Wait-CeleryWorkersOnline -TimeoutSeconds 60 -WorkerNodeNames @($dispatchWorkerNodeName, $coreWorkerNodeName)
        if (-not $celeryWorkersReady) {
            throw "Celery Worker 进程未在 60 秒内就绪（dispatch/core）。请检查 worker 窗口日志。"
        }
    }
    finally {
        Pop-Location
    }
}

if ($RunSeed) {
    Write-Host "导入演示数据 (scripts/seed_demo_kb.py) ..." -ForegroundColor Yellow
    Push-Location $backendDir
    try {
        uv run python scripts/seed_demo_kb.py
        if ($LASTEXITCODE -ne 0) {
            throw "导入演示数据失败（exit=$LASTEXITCODE）"
        }
    }
    finally {
        Pop-Location
    }
}

if (-not $SkipFrontend) {
    if ($SkipBackend) {
        Write-Host "提示：已跳过后端（-SkipBackend），前端将无法通过 /api 访问后端接口。" -ForegroundColor Yellow
    }
    else {
        Write-Host "等待后端依赖就绪（/api/v1/ready）..." -ForegroundColor Cyan
        $ok = Wait-BackendReady -TimeoutSeconds 30
        if (-not $ok) {
            throw "后端 API 未在 30 秒内就绪。请查看 backend-api 窗口日志（常见原因：依赖服务未启动、数据库未就绪、Windows 事件循环不兼容）。"
        }
    }

    Ensure-Command -Name "npm" -InstallHint "请安装 Node.js 20+ (包含 npm)"
    Push-Location $frontendDir
    try {
        if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
            Write-Host "检测到缺少 frontend/node_modules，执行 npm install..." -ForegroundColor Yellow
            npm install
            if ($LASTEXITCODE -ne 0) {
                throw "npm install 失败（exit=$LASTEXITCODE）"
            }
        }
        elseif ($Verbose) {
            Write-Host "已检测到 frontend/node_modules，跳过 npm install" -ForegroundColor DarkGray
        }

        Write-Host "执行前端生产构建 (npm run build)..." -ForegroundColor Yellow
        npm run build
        if ($LASTEXITCODE -ne 0) {
            throw "前端生产构建失败（exit=$LASTEXITCODE）"
        }
    }
    finally {
        Pop-Location
    }

    Start-Terminal -Title "frontend" -WorkingDirectory $frontendDir -Command "npm run start"
}

Write-Host ""
Write-Host "一键启动流程已完成，以下服务已启动（或启动中）:" -ForegroundColor Cyan
if (-not $SkipInfra) { Write-Host " - 基础依赖：Podman compose (infra/up.ps1)" -ForegroundColor Cyan }
if (-not $SkipBackend) { Write-Host " - 后端 API：uvicorn 生产参数监听 8000（Windows 启动期强制 SelectorEventLoopPolicy）" -ForegroundColor Cyan }
if (-not $SkipWorker) {
    Write-Host " - Celery Beat：独立进程（周期补偿调度）" -ForegroundColor Cyan
    Write-Host " - Celery Worker(dispatch)：队列 dispatch（默认并发 2）" -ForegroundColor Cyan
    Write-Host " - Celery Worker(core)：队列 ingestion,rebuild,default（默认并发 min(逻辑 CPU 核数, 8)）" -ForegroundColor Cyan
    Write-Host " - Celery Worker(noncore)：队列 research,export（默认并发 2）" -ForegroundColor Cyan
}
if (-not $SkipFrontend) { Write-Host " - 前端：Next.js 生产服务监听 3000" -ForegroundColor Cyan }
if ($RunSeed) { Write-Host " - 演示数据：已执行 seed_demo_kb.py" -ForegroundColor Cyan }


