param(
    [switch]$SkipInfra,
    [switch]$NoDetachInfra,
    [switch]$SkipBackend,
    [switch]$SkipWorker,
    [switch]$SkipFrontend,
    [switch]$SkipMigrate,
    [switch]$RunSeed,
    [switch]$Verbose
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"
$envFile = Join-Path $repoRoot ".env"

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

    $psCommand = "$Host.UI.RawUI.WindowTitle = '$Title'; Set-Location `"$WorkingDirectory`"; $Command"
    if ($Verbose) {
        $psCommand = "$Host.UI.RawUI.WindowTitle = '$Title'; Set-Location `"$WorkingDirectory`"; Write-Host '执行:' -ForegroundColor Yellow; Write-Host $Command -ForegroundColor DarkYellow; $Command"
    }
    Start-Process -FilePath "powershell" -ArgumentList "-NoExit", "-Command", $psCommand -WorkingDirectory $WorkingDirectory | Out-Null
}

Write-Host "加载环境变量 (.env) ..." -ForegroundColor Cyan
Import-DotEnv -Path $envFile
$env:PYTHONUNBUFFERED = "1"

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

$needBackend = (-not $SkipBackend) -or (-not $SkipWorker) -or $RunSeed
if ($needBackend) {
    Ensure-Command -Name "uv" -InstallHint "pip install uv"
    Push-Location $backendDir
    try {
        if (-not (Test-Path (Join-Path $backendDir ".venv"))) {
            Write-Host "检测到缺少 backend/.venv，执行 uv sync 安装依赖..." -ForegroundColor Yellow
            uv sync
        }
        elseif ($Verbose) {
            Write-Host "已检测到 backend/.venv，跳过 uv sync" -ForegroundColor DarkGray
        }

        if (-not $SkipMigrate) {
            Write-Host "执行数据库迁移 (alembic upgrade head)..." -ForegroundColor Yellow
            uv run alembic upgrade head
        }
        elseif ($Verbose) {
            Write-Host "已跳过迁移步骤" -ForegroundColor DarkGray
        }
    }
    finally {
        Pop-Location
    }
}

if (-not $SkipBackend) {
    Start-Terminal -Title "backend-api" -WorkingDirectory $backendDir -Command "uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
}

if (-not $SkipWorker) {
    Start-Terminal -Title "celery-worker" -WorkingDirectory $backendDir -Command "uv run celery -A app.worker.celery_app worker --loglevel=INFO --pool=solo"
}

if ($RunSeed) {
    Write-Host "导入演示数据 (scripts/seed_demo_kb.py) ..." -ForegroundColor Yellow
    Push-Location $backendDir
    try {
        uv run python scripts/seed_demo_kb.py
    }
    finally {
        Pop-Location
    }
}

if (-not $SkipFrontend) {
    Ensure-Command -Name "npm" -InstallHint "请安装 Node.js 20+ (包含 npm)"
    Push-Location $frontendDir
    try {
        if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
            Write-Host "检测到缺少 frontend/node_modules，执行 npm install..." -ForegroundColor Yellow
            npm install
        }
        elseif ($Verbose) {
            Write-Host "已检测到 frontend/node_modules，跳过 npm install" -ForegroundColor DarkGray
        }
    }
    finally {
        Pop-Location
    }

    Start-Terminal -Title "frontend" -WorkingDirectory $frontendDir -Command "npm run dev"
}

Write-Host "" 
Write-Host "一键启动流程已完成，以下服务已启动（或启动中）：" -ForegroundColor Cyan
if (-not $SkipInfra) { Write-Host " - 基础依赖：Podman compose (infra/up.ps1)" -ForegroundColor Cyan }
if (-not $SkipBackend) { Write-Host " - 后端 API：uvicorn 监听 8000" -ForegroundColor Cyan }
if (-not $SkipWorker) { Write-Host " - Celery Worker：Redis 队列" -ForegroundColor Cyan }
if (-not $SkipFrontend) { Write-Host " - 前端：Vite Dev Server 监听 5173" -ForegroundColor Cyan }
if ($RunSeed) { Write-Host " - 演示数据：已执行 seed_demo_kb.py" -ForegroundColor Cyan }
