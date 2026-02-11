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

    $psCommand = "`$Host.UI.RawUI.WindowTitle = '$Title'; Set-Location `"$WorkingDirectory`"; $Command"
    if ($Verbose) {
        $psCommand = "`$Host.UI.RawUI.WindowTitle = '$Title'; Set-Location `"$WorkingDirectory`"; Write-Host '执行:' -ForegroundColor Yellow; Write-Host $Command -ForegroundColor DarkYellow; $Command"
    }
    Start-Process -FilePath "powershell" -ArgumentList "-NoExit", "-Command", $psCommand -WorkingDirectory $WorkingDirectory | Out-Null
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

    # Prefer curl.exe to avoid PowerShell/system proxy quirks and to get status codes for 4xx/5xx.
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
        # If the server replied with a non-2xx, Invoke-WebRequest throws but carries the response.
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
    # /ready 会检查 Postgres 等关键依赖是否可用；比 /health 更能反映“前端可用”的状态。
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

function Get-CeleryWorkerCommand {
    $explicitPool = if ($env:CELERY_WORKER_POOL) { $env:CELERY_WORKER_POOL.Trim().ToLowerInvariant() } else { "" }

    $pool = if ($explicitPool) {
        $explicitPool
    }
    else {
        "threads"
    }

    $concurrency = if ($env:CELERY_WORKER_CONCURRENCY) {
        $env:CELERY_WORKER_CONCURRENCY
    }
    elseif ($pool -eq "threads") {
        $cpuCount = [Environment]::ProcessorCount
        if ($cpuCount -lt 1) { $cpuCount = 1 }
        [Math]::Min($cpuCount, 8).ToString()
    }
    else {
        "1"
    }

    if ($Verbose) {
        Write-Host "Celery Worker 参数：--pool=$pool --concurrency=$concurrency" -ForegroundColor DarkGray
    }

    return "uv run celery -A app.worker.celery_app worker --loglevel=INFO --pool=$pool --concurrency=$concurrency"
}
function Get-BackendApiCommand {
    $command = "uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --loop asyncio:SelectorEventLoop"
    if ($Verbose) {
        Write-Host "后端 API 参数：--loop asyncio:SelectorEventLoop（Windows + psycopg 兼容）" -ForegroundColor DarkGray
    }
    return $command
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
$shouldRunMigrate = $RunMigrate
if ($SkipMigrate) {
    Write-Host "参数 -SkipMigrate 仅为兼容保留；默认已跳过迁移。请优先使用 -RunMigrate 显式开启迁移。" -ForegroundColor DarkYellow
    if ($RunMigrate) {
        Write-Host "检测到 -RunMigrate 与 -SkipMigrate 同时传入，按 -SkipMigrate 优先，跳过迁移。" -ForegroundColor Yellow
    }
    $shouldRunMigrate = $false
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
    $workerCommand = Get-CeleryWorkerCommand
    Start-Terminal -Title "celery-worker" -WorkingDirectory $backendDir -Command $workerCommand
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
if (-not $SkipBackend) { Write-Host " - 后端 API：uvicorn 生产参数监听 8000（Windows 使用 SelectorEventLoop）" -ForegroundColor Cyan }
if (-not $SkipWorker) { Write-Host " - Celery Worker：threads 池（默认并发 min(逻辑 CPU 核数, 8)）" -ForegroundColor Cyan }
if (-not $SkipFrontend) { Write-Host " - 前端：Next.js 生产服务监听 3000" -ForegroundColor Cyan }
if ($RunSeed) { Write-Host " - 演示数据：已执行 seed_demo_kb.py" -ForegroundColor Cyan }


