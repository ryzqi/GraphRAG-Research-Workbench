# 最小验收脚本
# 用于验证 quickstart 的关键检查点

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

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  多知识库知识代理系统 - 验收检查" -ForegroundColor Cyan
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
Write-Host ""

# 4. 检查前端关键文件
Write-Host "4. 前端关键文件检查" -ForegroundColor Yellow
Write-Check "package.json 存在" (Test-Path "frontend/package.json")
Write-Check "vite.config.ts 存在" (Test-Path "frontend/vite.config.ts")
Write-Check "router.tsx 存在" (Test-Path "frontend/src/router.tsx")
Write-Host ""

# 5. 检查导出器
Write-Host "5. 导出器检查" -ForegroundColor Yellow
Write-Check "chat_exporter.py 存在" (Test-Path "backend/src/app/services/exporters/chat_exporter.py")
Write-Check "research_exporter.py 存在" (Test-Path "backend/src/app/services/exporters/research_exporter.py")
Write-Check "evaluation_exporter.py 存在" (Test-Path "backend/src/app/services/exporters/evaluation_exporter.py")
Write-Host ""

# 6. 检查文档
Write-Host "6. 文档检查" -ForegroundColor Yellow
Write-Check "architecture.md 存在" (Test-Path "docs/architecture.md")
Write-Check "quickstart.md 存在" (Test-Path "specs/001-multi-kb-agent-collab/quickstart.md")
Write-Check "README.md 存在" (Test-Path "README.md")
Write-Host ""

# 7. 服务连通性检查（可选）
if (-not $SkipInfra) {
    Write-Host "7. 服务连通性检查" -ForegroundColor Yellow

    # 后端 API
    $apiHealth = Test-Endpoint "http://localhost:8000/api/v1/health" "Backend API"
    Write-Check "后端 API 健康检查" $apiHealth "请确保后端服务已启动: uv run uvicorn app.main:app"

    # 前端
    $frontendHealth = Test-Endpoint "http://localhost:5173" "Frontend"
    Write-Check "前端服务" $frontendHealth "请确保前端服务已启动: npm run dev"

    # OpenAPI 文档
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
