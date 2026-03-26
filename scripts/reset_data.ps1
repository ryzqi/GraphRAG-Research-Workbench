param(
    [switch]$Force,
    [switch]$SkipMigrate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $Force) {
    throw "This script destroys local PostgreSQL/Milvus/Redis data. Re-run with -Force to continue."
}

function Import-DotEnv {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing $Path. Copy .env.example to .env before running reset."
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

function Invoke-InfraCompose {
    param([Parameter(Mandatory = $true)][string[]]$Args)

    if (Get-Command podman -ErrorAction SilentlyContinue) {
        & podman compose -f $script:composeFile @Args
        if ($LASTEXITCODE -ne 0) {
            throw "podman compose failed (exit=$LASTEXITCODE)."
        }
        return
    }

    if (Get-Command podman-compose -ErrorAction SilentlyContinue) {
        & podman-compose -f $script:composeFile @Args
        if ($LASTEXITCODE -ne 0) {
            throw "podman-compose failed (exit=$LASTEXITCODE)."
        }
        return
    }

    throw "Neither podman nor podman-compose is available."
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$infraDir = Join-Path $repoRoot "infra"
$backendDir = Join-Path $repoRoot "backend"
$script:composeFile = Join-Path $infraDir "podman-compose.yml"
$envFile = Join-Path $repoRoot ".env"

Import-DotEnv -Path $envFile

Write-Host "[1/5] Stop infrastructure and remove named volumes..." -ForegroundColor Yellow
Push-Location $repoRoot
try {
    Invoke-InfraCompose -Args @("down", "-v")
}
finally {
    Pop-Location
}

Write-Host "[2/5] Remove local Redis/Milvus metadata directories..." -ForegroundColor Yellow
$pathsToClear = @(
    (Join-Path $infraDir "data/redis"),
    (Join-Path $infraDir "data/milvus"),
    (Join-Path $infraDir "data/etcd"),
    (Join-Path $infraDir "data/searxng"),
    (Join-Path $infraDir "data/searxng-valkey")
)
foreach ($pathToClear in $pathsToClear) {
    if (Test-Path -LiteralPath $pathToClear) {
        Remove-Item -LiteralPath $pathToClear -Recurse -Force
    }
    New-Item -ItemType Directory -Path $pathToClear -Force | Out-Null
}

Write-Host "[3/5] Restart infrastructure..." -ForegroundColor Yellow
Push-Location $repoRoot
try {
    Invoke-InfraCompose -Args @("up", "-d")
}
finally {
    Pop-Location
}

if (-not $SkipMigrate) {
    Write-Host "[4/5] Run backend migrations..." -ForegroundColor Yellow
    Push-Location $backendDir
    try {
        & uv run alembic upgrade head
        if ($LASTEXITCODE -ne 0) {
            throw "alembic upgrade failed (exit=$LASTEXITCODE)."
        }
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Host "[4/5] Skip migrations (--SkipMigrate)." -ForegroundColor DarkYellow
}

Write-Host "[5/5] Reset completed. PostgreSQL + Milvus + Redis data are cleared." -ForegroundColor Green
if ($SkipMigrate) {
    Write-Host "Run 'cd backend; uv run alembic upgrade head' before ingesting new data." -ForegroundColor DarkYellow
}
