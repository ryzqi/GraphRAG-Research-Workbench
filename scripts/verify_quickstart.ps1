# 最小验收脚本
# 用于验证快速启动流程的关键项

param(
    [switch]$SkipInfra,
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"
$script:passed = 0
$script:failed = 0

function Write-Check {
    param([string]$Name, [bool]$Success, [string]$Message = "")
    if ($Success) {
        Write-Host "[PASS] $Name" -ForegroundColor Green
        $script:passed++
    } else {
        Write-Host "[FAIL] $Name" -ForegroundColor Red
        if ($Message) { Write-Host "       $Message" -ForegroundColor Yellow }
        $script:failed++
    }
}

function Test-Endpoint {
    param([string]$Url, [string]$Name)
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Test-SearXngJsonSearch {
    param(
        [string]$BaseUrl,
        [string[]]$Engines = @()
    )
    try {
        $query = "q=OpenAI&format=json"
        if ($Engines.Count -gt 0) {
            $query += "&engines=" + [System.Uri]::EscapeDataString(($Engines -join ","))
        }
        $resp = Invoke-RestMethod -Uri ($BaseUrl.TrimEnd('/') + "/search?" + $query) -UseBasicParsing -Headers @{ "User-Agent" = "Mozilla/5.0 quickstart-check" } -TimeoutSec 15
        return @($resp.results).Count -gt 0
    } catch {
        return $false
    }
}

function Get-DotEnvValue {
    param(
        [string]$Path,
        [string]$Key
    )

    if (-not (Test-Path $Path)) {
        return $null
    }

    $prefix = "$Key="
    foreach ($line in Get-Content -Path $Path -Encoding UTF8) {
        if ($line.StartsWith($prefix)) {
            return $line.Substring($prefix.Length).Trim()
        }
    }

    return $null
}

function Get-SearXngDefaultEngines {
    param([string]$EnvPath)

    $raw = Get-DotEnvValue -Path $EnvPath -Key "SEARXNG_DEFAULT_ENGINES"
    if ([string]::IsNullOrWhiteSpace($raw) -or $raw -eq "[]") {
        return @()
    }

    try {
        $parsed = $raw | ConvertFrom-Json
        if ($parsed -is [System.Array]) {
            return @($parsed | ForEach-Object { "$_".Trim() } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        }
    } catch {
    }

    return @($raw.Split(",") | ForEach-Object { $_.Trim().Trim('"').Trim("'") } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Get-SearXngKeepOnlyEngines {
    param([string]$SettingsPath)

    if (-not (Test-Path $SettingsPath)) {
        return @()
    }

    $engines = New-Object System.Collections.Generic.List[string]
    $insideKeepOnly = $false
    foreach ($line in Get-Content -Path $SettingsPath -Encoding UTF8) {
        if ($line -match '^\s*keep_only:\s*$') {
            $insideKeepOnly = $true
            continue
        }

        if (-not $insideKeepOnly) {
            continue
        }

        if ($line -match '^\s*-\s*(.+?)\s*$') {
            $engines.Add($Matches[1].Trim())
            continue
        }

        if ($line -match '^\s*\S') {
            break
        }

        if ($line.Trim().Length -eq 0) {
            continue
        }

        break
    }

    return @($engines)
}

function Get-SearXngImageEngineCatalogCount {
    param([string]$ContainerName = "mkb_searxng")

    if (-not (Get-Command podman -ErrorAction SilentlyContinue)) {
        return $null
    }

    try {
        $count = & podman exec $ContainerName sh -lc "grep -c '^  - name:' /usr/local/searxng/searx/settings.yml"
        if ($LASTEXITCODE -ne 0) {
            return $null
        }
        $parsed = 0
        if ([int]::TryParse(($count | Out-String).Trim(), [ref]$parsed)) {
            return $parsed
        }
    } catch {
        return $null
    }

    return $null
}

function Get-SearXngActiveEngineCount {
    param(
        [string]$BaseUrl,
        [string]$EnvPath,
        [string]$SettingsPath,
        [string]$ContainerName = "mkb_searxng"
    )

    try {
        $config = Invoke-RestMethod -Uri ($BaseUrl.TrimEnd('/') + "/config") -UseBasicParsing -TimeoutSec 10
        $engines = @($config.engines)
        if ($engines.Count -gt 0) {
            $enabledCount = @($engines | Where-Object { $_.enabled -eq $true }).Count
            return [PSCustomObject]@{
                Count   = $enabledCount
                Mode    = "runtime_config"
                Message = "运行态 /config 显示当前启用了 $enabledCount / $($engines.Count) 个引擎。"
            }
        }
    } catch {
    }

    $imageCatalogCount = Get-SearXngImageEngineCatalogCount -ContainerName $ContainerName
    if ($imageCatalogCount -gt 0) {
        $defaultEngines = Get-SearXngDefaultEngines -EnvPath $EnvPath
        if ($defaultEngines.Count -gt 0) {
            return [PSCustomObject]@{
                Count   = $defaultEngines.Count
                Mode    = "env_allowlist"
                Message = "运行态 /config 暂不可读；按 .env 推导当前请求默认会显式指定 $($defaultEngines.Count) 个引擎。"
            }
        }

        $keepOnlyEngines = Get-SearXngKeepOnlyEngines -SettingsPath $SettingsPath
        if ($keepOnlyEngines.Count -gt 0) {
            return [PSCustomObject]@{
                Count   = $keepOnlyEngines.Count
                Mode    = "keep_only"
                Message = "运行态 /config 暂不可读；按 settings.yml 推导当前 keep_only 白名单为 $($keepOnlyEngines.Count) 个引擎。"
            }
        }

        return [PSCustomObject]@{
            Count   = $imageCatalogCount
            Mode    = "full_default_catalog"
            Message = "运行态 /config 暂不可读；按当前配置推导 SearXNG 将使用全量默认引擎集（镜像默认目录共 $imageCatalogCount 个引擎）。"
        }
    }

    return [PSCustomObject]@{
        Count   = $null
        Mode    = "unknown"
        Message = "未能推导当前活跃引擎数；请检查 /config、mkb_searxng 容器状态，并手动核对容器内 /usr/local/searxng/searx/settings.yml。"
    }
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  知识代理系统 - 验收检查" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. 检查环境文件
Write-Host "1. 环境配置检查" -ForegroundColor Yellow
Write-Check ".env 文件存在" (Test-Path ".env")
Write-Check ".env.example 文件存在" (Test-Path ".env.example")
Write-Host ""

# 2. 检查目录结构
Write-Host "2. 目录结构检查" -ForegroundColor Yellow
Write-Check "backend 目录存在" (Test-Path "backend")
Write-Check "frontend 目录存在" (Test-Path "frontend")
Write-Check "infra 目录存在" (Test-Path "infra")
Write-Check "docs 目录存在" (Test-Path "docs")
Write-Host ""

# 3. 检查后端关键文件
Write-Host "3. 后端关键文件检查" -ForegroundColor Yellow
Write-Check "main.py 存在" (Test-Path "backend/src/app/main.py")
Write-Check "settings.py 存在" (Test-Path "backend/src/app/core/settings.py")
Write-Check "celery_app.py 存在" (Test-Path "backend/src/app/worker/celery_app.py")
Write-Check "alembic 配置存在" (Test-Path "backend/alembic/env.py")
Write-Check "alembic 模板存在" (Test-Path "backend/alembic/script.py.mako")
Write-Host ""

# 4. 检查前端关键文件
Write-Host "4. 前端关键文件检查" -ForegroundColor Yellow
Write-Check "package.json 存在" (Test-Path "frontend/package.json")
Write-Check "next.config.mjs 存在" (Test-Path "frontend/next.config.mjs")
Write-Check "App Router layout 存在" (Test-Path "frontend/src/app/layout.tsx")
Write-Host ""

# 5. 检查导出器
Write-Host "5. 导出器检查" -ForegroundColor Yellow
Write-Check "chat_exporter.py 存在" (Test-Path "backend/src/app/services/exporters/chat_exporter.py")
Write-Check "research_exporter.py 存在" (Test-Path "backend/src/app/services/exporters/research_exporter.py")
Write-Host ""

# 6. 检查文档
Write-Host "6. 文档检查" -ForegroundColor Yellow
Write-Check "architecture.md 存在" (Test-Path "docs/architecture.md")
Write-Check "Research API 契约文档存在" (Test-Path "docs/api_contract_research.md")
Write-Check "README.md 存在" (Test-Path "README.md")
Write-Host ""

# 7. 服务连通性检查（可选）
if (-not $SkipInfra) {
    Write-Host "7. 服务连通性检查" -ForegroundColor Yellow

    $searxngPort = if ($env:SEARXNG_PORT) { $env:SEARXNG_PORT } else { "18080" }
    $searxngBaseUrl = "http://127.0.0.1:$searxngPort"
    $searxngSettingsPath = "infra/searxng/config/settings.yml"
    $searxngEngines = Get-SearXngDefaultEngines -EnvPath ".env"
    $searxngConfig = Test-Endpoint "$searxngBaseUrl/config" "SearXNG Config"
    Write-Check "SearXNG 配置页" $searxngConfig "请先运行: pwsh -ExecutionPolicy Bypass -File .\scripts\start_all.ps1"
    $searxngActiveEngines = Get-SearXngActiveEngineCount -BaseUrl $searxngBaseUrl -EnvPath ".env" -SettingsPath $searxngSettingsPath
    Write-Check "SearXNG 活跃引擎数" ($null -ne $searxngActiveEngines.Count -and $searxngActiveEngines.Count -gt 0) $searxngActiveEngines.Message
    $searxngSearch = Test-SearXngJsonSearch -BaseUrl $searxngBaseUrl -Engines $searxngEngines
    Write-Check "SearXNG JSON 搜索 API" $searxngSearch "请检查 infra/searxng/config/settings.yml 中 search.formats 是否包含 json；若 API 可访问但 results 为空且容器日志出现 ConnectTimeout/ConnectError，请检查 Podman 外网连通性或代理配置（例如宿主机代理是否可从容器访问）。"

    # 后端接口
    $apiHealth = Test-Endpoint "http://localhost:8000/api/v1/health" "Backend API"
    Write-Check "后端 API 健康检查" $apiHealth "请先运行: pwsh -ExecutionPolicy Bypass -File .\scripts\start_all.ps1（或仅后端命令: uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --loop app.core.uvicorn_loop:windows_selector_loop_factory）"

    # 前端服务
    $frontendHealth = Test-Endpoint "http://localhost:3000" "Frontend"
    Write-Check "前端服务" $frontendHealth "请确保前端服务已启动: npm run start"

    # OpenAPI 文档页
    $docsHealth = Test-Endpoint "http://localhost:8000/docs" "OpenAPI Docs"
    Write-Check "OpenAPI 文档" $docsHealth

    Write-Host ""
}

# 8. 数据库迁移检查
Write-Host "8. 数据库迁移文件检查" -ForegroundColor Yellow
$migrations = Get-ChildItem -Path "backend/alembic/versions" -Filter "*.py" -ErrorAction SilentlyContinue
$migrationCount = if ($migrations) { $migrations.Count } else { 0 }
Write-Check "迁移文件存在 ($migrationCount 个)" ($migrationCount -gt 0)
Write-Host ""

# 汇总
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  验收结果汇总" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "通过: $script:passed" -ForegroundColor Green
Write-Host "失败: $script:failed" -ForegroundColor $(if ($script:failed -gt 0) { "Red" } else { "Green" })
Write-Host ""

if ($script:failed -gt 0) {
    Write-Host "部分检查未通过，请根据提示修复问题。" -ForegroundColor Yellow
    exit 1
} else {
    Write-Host "所有检查通过！" -ForegroundColor Green
    exit 0
}
