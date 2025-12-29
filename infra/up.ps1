param(
  [switch]$NoDetach
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Import-DotEnv {
  param([Parameter(Mandatory = $true)][string]$Path)

  if (-not (Test-Path -LiteralPath $Path)) {
    throw "未找到 $Path。请先从 .env.example 复制并填写为 .env。"
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

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$composeFile = Join-Path $PSScriptRoot "podman-compose.yml"
$envFile = Join-Path $repoRoot ".env"

Import-DotEnv -Path $envFile

Push-Location $repoRoot
try {
  $detachArgs = @()
  if (-not $NoDetach) { $detachArgs += @("-d") }

  if (Get-Command podman -ErrorAction SilentlyContinue) {
    & podman compose -f $composeFile up @detachArgs
    if ($LASTEXITCODE -ne 0) { throw "podman compose 执行失败（exit=$LASTEXITCODE）" }
  }
  elseif (Get-Command podman-compose -ErrorAction SilentlyContinue) {
    & podman-compose -f $composeFile up @detachArgs
    if ($LASTEXITCODE -ne 0) { throw "podman-compose 执行失败（exit=$LASTEXITCODE）" }
  }
  else {
    throw "未找到 podman 或 podman-compose。请先安装 Podman（建议 Podman Desktop）。"
  }

  Write-Host "基础依赖已启动（Postgres/Redis/Milvus）。"
}
finally {
  Pop-Location
}

