Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$backendDir = Join-Path $repoRoot "backend"
$backendSrcDir = Join-Path $backendDir "src"
$celeryExe = Join-Path $backendDir ".venv\Scripts\celery.exe"
$envFile = Join-Path $repoRoot ".env"

function Import-DotEnv {
    param([Parameter(Mandatory = $true)][string]$Path)

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

Import-DotEnv -Path $envFile
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = $backendSrcDir

Set-Location $backendSrcDir
& $celeryExe -A app.worker.celery_app worker -n worker.noncore@%h --pool=threads --concurrency=2 --prefetch-multiplier=1 -Q research,export
