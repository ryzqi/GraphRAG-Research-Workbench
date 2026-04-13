param(
  [switch]$NoDetach
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Import-DotEnv {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [switch]$Optional,
    [switch]$SkipExisting
  )

  if (-not (Test-Path -LiteralPath $Path)) {
    if ($Optional) {
      return
    }
    throw "未找到 $Path。请先复制 infra/env/dev.env.example 为 infra/env/dev.env，或直接使用示例文件。"
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

    if ($key.Length -eq 0) {
      return
    }
    if ($SkipExisting) {
      $existing = [Environment]::GetEnvironmentVariable($key)
      if (-not [string]::IsNullOrWhiteSpace($existing)) {
        return
      }
    }

    Set-Item -Path ("Env:" + $key) -Value $value
  }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$devEnvExamplePath = Join-Path $PSScriptRoot "env\dev.env.example"
$devEnvPath = Join-Path $PSScriptRoot "env\dev.env"
$composeFiles = @(
  (Join-Path $PSScriptRoot "podman-compose.base.yml"),
  (Join-Path $PSScriptRoot "podman-compose.dev.yml")
)

Write-Host "infra/up.ps1 仅用于本地开发基础设施。生产部署请改用 podman-compose.base.yml + podman-compose.prod.example.yml 并参考 docs/ops/config-and-secrets.md。" -ForegroundColor Yellow

Import-DotEnv -Path $devEnvExamplePath
Import-DotEnv -Path $devEnvPath -Optional

$requiredDirs = @(
  (Join-Path $PSScriptRoot "data\searxng"),
  (Join-Path $PSScriptRoot "data\searxng-valkey")
)

foreach ($dir in $requiredDirs) {
  New-Item -ItemType Directory -Path $dir -Force | Out-Null
}

Push-Location $repoRoot
try {
  $detachArgs = @()
  if (-not $NoDetach) { $detachArgs += @("-d") }

  $composeArgs = @()
  foreach ($composeFile in $composeFiles) {
    $composeArgs += @("-f", $composeFile)
  }

  if (Get-Command podman -ErrorAction SilentlyContinue) {
    & podman compose @composeArgs up @detachArgs
    if ($LASTEXITCODE -ne 0) { throw "podman compose 执行失败（exit=$LASTEXITCODE）" }
  }
  elseif (Get-Command podman-compose -ErrorAction SilentlyContinue) {
    & podman-compose @composeArgs up @detachArgs
    if ($LASTEXITCODE -ne 0) { throw "podman-compose 执行失败（exit=$LASTEXITCODE）" }
  }
  else {
    throw "未找到 podman 或 podman-compose。请先安装 Podman（建议 Podman Desktop）。"
  }

  Write-Host "本地开发基础依赖已启动（Postgres/Redis/Etcd/MinIO/Milvus/SearXNG/Valkey）。"
}
finally {
  Pop-Location
}
